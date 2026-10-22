'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const utf8 = new TextEncoder();
  let pair;
  const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/, '');
  function openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('oakgate-pos-device-v1', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('keys');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('Browser storage is unavailable. Use a regular browser window.'));
      request.onblocked = () => reject(new Error('Close other POS tabs and try again.'));
    });
  }
  async function keyStore(value) {
    const db = await openDB();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('keys', value ? 'readwrite' : 'readonly');
        const req = tx.objectStore('keys').get('device');
        let result;
        req.onsuccess = () => {
          result = req.result;
          // Read/write transactions serialize this check across tabs, including
          // browsers without Web Locks. Never overwrite a registered key.
          if (value && !result) { tx.objectStore('keys').put(value, 'device'); result = value; }
        };
        tx.oncomplete = () => resolve(result);
        tx.onerror = tx.onabort = () => reject(new Error('Could not persist this browser’s device key.'));
      });
    } finally { db.close(); }
  }
  async function device(create = false) {
    if (!isSecureContext || !crypto.subtle) throw new Error('Use the HTTPS POS address to activate this device.');
    let stored = await keyStore();
    if (!stored && create) {
      const generated = await crypto.subtle.generateKey({name:'ECDSA', namedCurve:'P-256'}, false, ['sign','verify']);
      // Persist and re-read before enrollment. A failed write must not bind an unusable key.
      await keyStore(generated);
      stored = await keyStore();
    }
    if (!stored || stored.privateKey.extractable !== false) throw new Error('This browser’s device key is missing. Revoke this terminal in Preferences and create a new key.');
    const sample = crypto.getRandomValues(new Uint8Array(32));
    const signature = await crypto.subtle.sign({name:'ECDSA', hash:'SHA-256'}, stored.privateKey, sample);
    if (!await crypto.subtle.verify({name:'ECDSA', hash:'SHA-256'}, stored.publicKey, signature, sample)) throw new Error('Device key verification failed.');
    return stored;
  }
  async function api(operation, data) {
    const response = await fetch('/api/' + operation, {method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', cache:'no-store', body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Please try again shortly.');
    return result;
  }
  async function proof(challenge, operation, publicKey) {
    const fields = JSON.parse(challenge.message);
    // Only sign the agreed domain, audience and operation. The server checks the entire transcript.
    if (!Array.isArray(fields) || fields.length !== 10 || fields[0] !== 'oakgate-pos-proof-v1' ||
        fields[1] !== location.origin || fields[4] !== 'POST' || fields[5] !== '/api/pos/v1/' + operation ||
        fields[6] !== '' || fields[8] !== challenge.challenge || fields[9] < Date.now()/1000 - 5 ||
        fields[9] > Date.now()/1000 + 90) throw new Error('Invalid device challenge. Check this device’s clock and POS address.');
    const expectedBody = operation === 'activate' ? JSON.stringify([fields[2], publicKey]) : '{}';
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', utf8.encode(expectedBody))), x => x.toString(16).padStart(2,'0')).join('');
    if (fields[7] !== hash) throw new Error('Invalid device challenge.');
    return {challenge:challenge.challenge, signature:b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'}, pair.privateKey, utf8.encode(challenge.message)))};
  }
  async function signed(operation) {
    const challenge = await api('challenges', {operation});
    return api(operation, await proof(challenge, operation));
  }
  async function showTerminal() {
    const config = await signed('config');
    $('heading').textContent = config.name;
    $('fingerprint').textContent = config.fingerprint.slice(0,16);
    $('status').textContent = 'This browser is activated.';
    $('activation').hidden = true; $('terminal').hidden = false; $('forget').hidden = true;
  }
  async function busy(action) {
    $('error').textContent = '';
    document.querySelectorAll('button').forEach(button => {button.disabled=true;});
    try { await action(); } catch (error) {
      $('error').textContent = error.message || 'Please try again shortly.';
    } finally { document.querySelectorAll('button').forEach(button => {button.disabled=false;}); }
  }
  $('activation').addEventListener('submit', event => {
    event.preventDefault();
    busy(async () => {
      // Web Locks serializes enrollment across tabs where available. The server
      // still atomically binds a credential and rejects a conflicting browser key.
      const activate = async () => {
        pair = await device(true);
        const credential = $('credential').value.trim();
        const public_key = b64(await crypto.subtle.exportKey('raw', pair.publicKey));
        const challenge = await api('activation-challenges', {credential, public_key});
        await api('activate', {credential, public_key, ...await proof(challenge, 'activate', public_key)});
        $('credential').value = '';
        $('forget').hidden = false;
        await showTerminal();
      };
      if (navigator.locks) await navigator.locks.request('oakgate-pos-enrollment', activate);
      else await activate();
    });
  });
  $('logout').addEventListener('click', () => busy(async () => {
    $('forget').hidden = false;
    await signed('logout');
    location.reload();
  }));
  $('forget').addEventListener('click', () => busy(async () => {
    await api('forget', {});
    location.reload();
  }));
  busy(async () => {
    const response = await fetch('/api/session', {cache:'no-store', credentials:'same-origin'});
    const state = await response.json();
    if (!state.enabled) {
      $('heading').textContent = 'Point of sale is disabled';
      $('status').textContent = 'Contact the operator to enable this terminal service.';
      $('forget').hidden = false;
      return;
    }
    if (state.session_present) {
      $('forget').hidden = false;
      pair = await device();
      await showTerminal();
    } else {
      $('status').textContent = 'Use a dedicated device to receive on behalf of your Acorn.';
      $('activation').hidden = false;
    }
  });
})();
