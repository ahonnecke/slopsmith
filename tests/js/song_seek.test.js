// Verify static/app.js emits `song:seek` for every audio repositioning,
// with `{ from, to, reason }` payload. Plugins (notedetect detection-
// suppression during seek transients) consume this contract.
//
// Same isolation strategy as loop_restart.test.js — extract the relevant
// functions from app.js by brace-matching and run them in a vm sandbox.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const APP_JS = path.join(__dirname, '..', '..', 'static', 'app.js');

function extractFunction(src, signature) {
    const start = src.indexOf(signature);
    if (start === -1) throw new Error(`extractFunction: '${signature}' not found in app.js`);
    const openBrace = src.indexOf('{', start);
    let depth = 1;
    let i = openBrace + 1;
    while (i < src.length && depth > 0) {
        const ch = src[i];
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        i++;
    }
    if (depth !== 0) throw new Error(`extractFunction: unbalanced braces after '${signature}'`);
    return src.slice(start, i);
}

function buildSandbox({ juceMode = false, currentTime = 10 } = {}) {
    const emitCalls = [];
    const audio = {
        get currentTime() { return audio._t; },
        set currentTime(v) { audio._t = v; },
        _t: currentTime,
    };
    const jucePlayer = {
        currentTime: currentTime,
        seek(s) {
            // Async like the real one; mutate currentTime so subsequent
            // _audioTime() reads see the new value.
            return Promise.resolve().then(() => { jucePlayer.currentTime = s; });
        },
    };
    const sandbox = {
        audio,
        jucePlayer,
        window: {
            _juceMode: juceMode,
            slopsmith: {
                emit(event, detail) { emitCalls.push({ event, detail }); },
            },
        },
        __emitCalls: emitCalls,
    };
    vm.createContext(sandbox);
    return sandbox;
}

function loadFunctions(sandbox, src) {
    const code = `
        let _audioSeekChain = Promise.resolve();
        let _audioSeekGen = 0;
        ${extractFunction(src, 'function _audioTime()')}
        ${extractFunction(src, 'function _audioDuration()')}
        ${extractFunction(src, 'async function _audioSeek(')}
        ${extractFunction(src, 'async function seekBy(')}
        globalThis.__audioSeek = _audioSeek;
        globalThis.__seekBy = seekBy;
        globalThis.__bumpGen = () => { _audioSeekGen++; _audioSeekChain = Promise.resolve(); };
    `;
    vm.runInContext(code, sandbox);
}

test('_audioSeek emits song:seek with from/to/reason (HTML5 path)', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: false, currentTime: 10 });
    loadFunctions(sandbox, src);

    await sandbox.__audioSeek(42, 'unit-test');

    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 1);
    assert.equal(seeks[0].detail.from, 10);
    assert.equal(seeks[0].detail.to, 42);
    assert.equal(seeks[0].detail.reason, 'unit-test');
    assert.equal(sandbox.audio._t, 42, 'HTML5 audio.currentTime must be assigned');
});

test('_audioSeek emits song:seek (JUCE path) after seek promise resolves', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: true, currentTime: 5 });
    loadFunctions(sandbox, src);

    await sandbox.__audioSeek(99, 'juce-test');

    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 1);
    assert.equal(seeks[0].detail.from, 5);
    assert.equal(seeks[0].detail.to, 99);
    assert.equal(seeks[0].detail.reason, 'juce-test');
    assert.equal(sandbox.jucePlayer.currentTime, 99, 'JUCE player position must be advanced');
});

test('concurrent _audioSeek calls serialize and capture from atomically', async () => {
    // Without serialization, two overlapping JUCE seeks would both read
    // `from` before either resolved, making the second emit's `from` stale.
    // The chain ensures each call's from/to bracket only its own seek.
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: true, currentTime: 0 });
    // Make jucePlayer.seek slow so the second call genuinely overlaps the
    // first if there's no serialization.
    sandbox.jucePlayer.seek = (s) => new Promise((resolve) => setTimeout(() => {
        sandbox.jucePlayer.currentTime = s;
        resolve();
    }, 5));
    loadFunctions(sandbox, src);

    // Fire two seeks back-to-back without awaiting the first.
    const p1 = sandbox.__audioSeek(10, 'first');
    const p2 = sandbox.__audioSeek(20, 'second');
    await Promise.all([p1, p2]);

    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 2);
    // First seek: from=0 (initial), to=10
    assert.equal(seeks[0].detail.from, 0);
    assert.equal(seeks[0].detail.to, 10);
    assert.equal(seeks[0].detail.reason, 'first');
    // Second seek: from=10 (post-first, captured INSIDE the chain), to=20
    assert.equal(seeks[1].detail.from, 10, 'second seek must capture from after first resolved');
    assert.equal(seeks[1].detail.to, 20);
    assert.equal(seeks[1].detail.reason, 'second');
});

test('queued seeks cancel cleanly when generation bumps mid-flight', async () => {
    // Simulates song teardown: a seek is enqueued, then the generation
    // bumps before the seek's chain callback runs. The pending callback
    // must bail out — no song:seek emit, no mutation of the new session's
    // currentTime.
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: true, currentTime: 5 });
    sandbox.jucePlayer.seek = (s) => new Promise((resolve) => setTimeout(() => {
        sandbox.jucePlayer.currentTime = s;
        resolve();
    }, 5));
    loadFunctions(sandbox, src);

    // Enqueue a seek but bump the generation before the chain's microtask runs.
    const p = sandbox.__audioSeek(99, 'cancel-test');
    sandbox.__bumpGen();
    const result = await p;

    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 0, 'cancelled seek must not emit song:seek');
    assert.equal(sandbox.jucePlayer.currentTime, 5, 'cancelled seek must not advance currentTime');
    assert.equal(result.completed, false, 'cancelled seek must resolve to {completed: false} so callers can bail');
});

test('queued seek bails when generation bumps DURING the JUCE seek', async () => {
    // Covers the second gen-check (the one after `await jucePlayer.seek`).
    // The previous test bumps before the chain callback starts; this one
    // lets the callback enter, reach the seek await, and then bumps so the
    // post-await guard is what catches the cancellation.
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: true, currentTime: 5 });
    let bumpedDuringSeek = false;
    sandbox.jucePlayer.seek = (s) => new Promise((resolve) => setTimeout(() => {
        sandbox.jucePlayer.currentTime = s;
        // Bump while the seek is mid-flight: we're past the first guard
        // (it ran when the chain callback entered), but before the second.
        if (!bumpedDuringSeek) { sandbox.__bumpGen(); bumpedDuringSeek = true; }
        resolve();
    }, 5));
    loadFunctions(sandbox, src);

    const result = await sandbox.__audioSeek(99, 'mid-seek-cancel');

    assert.equal(bumpedDuringSeek, true, 'sanity: bump must have fired inside the seek');
    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 0, 'mid-seek cancel must not emit song:seek');
    assert.equal(result.completed, false, 'mid-seek cancel must resolve to {completed: false}');
});

test('_audioSeek resolves to {completed, from, to} on a successful run', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: false, currentTime: 5 });
    loadFunctions(sandbox, src);
    const result = await sandbox.__audioSeek(10, 'success-test');
    assert.equal(result.completed, true, 'completed seek must resolve to completed:true');
    assert.equal(result.from, 5, 'from must be the pre-seek clock');
    assert.equal(result.to, 10, 'to must be the verified post-seek clock');
});

test('_audioSeek emits the verified post-seek clock when JUCE rolls back', async () => {
    // Regression: `to` must reflect the actual position after seek, not
    // the requested `s`. JUCE may clamp or no-op a seek (engine state
    // mismatch, end-of-track, etc.); plugins that act on `to` would
    // otherwise see a phantom jump.
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: true, currentTime: 7 });
    sandbox.jucePlayer.seek = (s) => Promise.resolve(); // no-op: currentTime stays at 7
    loadFunctions(sandbox, src);

    await sandbox.__audioSeek(42, 'rollback-test');

    const seek = sandbox.__emitCalls.find((c) => c.event === 'song:seek');
    assert.equal(seek.detail.from, 7);
    assert.equal(seek.detail.to, 7, 'to must equal post-seek clock, not requested s');
    assert.equal(seek.detail.reason, 'rollback-test');
});

test('_audioSeek without reason emits reason: null', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox();
    loadFunctions(sandbox, src);

    await sandbox.__audioSeek(20);

    const seek = sandbox.__emitCalls.find((c) => c.event === 'song:seek');
    assert.equal(seek.detail.reason, null);
});

test('seekBy routes through _audioSeek with reason "seek-by"', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: false, currentTime: 10 });
    loadFunctions(sandbox, src);

    await sandbox.__seekBy(5);

    const seeks = sandbox.__emitCalls.filter((c) => c.event === 'song:seek');
    assert.equal(seeks.length, 1, 'seekBy must trigger exactly one song:seek emit');
    assert.equal(seeks[0].detail.from, 10);
    assert.equal(seeks[0].detail.to, 15);
    assert.equal(seeks[0].detail.reason, 'seek-by');
});

test('seekBy floors at zero (does not seek to negative time)', async () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    const sandbox = buildSandbox({ juceMode: false, currentTime: 2 });
    loadFunctions(sandbox, src);

    await sandbox.__seekBy(-10);

    const seek = sandbox.__emitCalls.find((c) => c.event === 'song:seek');
    assert.equal(seek.detail.to, 0);
});

test('every documented seek callsite passes a reason', () => {
    // Source-order assertion: every _audioSeek call outside the
    // implementation must pass a kebab-case reason string. Catches a
    // future contributor adding a new seek path without threading the
    // reason. Line-based — regex argument capture can't balance parens
    // through Math.max/_audioTime calls.
    const src = fs.readFileSync(APP_JS, 'utf8');
    const fnSrc = extractFunction(src, 'async function _audioSeek(');
    const withoutImpl = src.replace(fnSrc, '');
    const callLines = withoutImpl.split('\n').filter((l) => /_audioSeek\(/.test(l));
    assert.ok(callLines.length >= 5, `expected ≥5 _audioSeek call lines, found ${callLines.length}`);
    for (const line of callLines) {
        assert.match(
            line,
            /['"][a-z]+(?:-[a-z]+)+['"]/,
            `_audioSeek call missing kebab-case reason arg: ${line.trim()}`,
        );
    }
});
