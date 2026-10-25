<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=true; section>
<#if section == "header">Sign in with your NFC card
<#elseif section == "form">
<form id="oakgate-nfc" action="${url.loginAction}" method="post" autocomplete="off">
<p id="nfc-status" role="status">Tap Read card, then hold your card against the phone.</p>
<button id="nfc-read" type="button">Read card</button>
<input id="nfc-card" name="card" type="hidden" value="">
<label for="nfc-pin">Four-digit PIN</label>
<input id="nfc-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="off">
<p>Leave the PIN blank only if you enabled card-only sign-in in your wallet settings.</p>
<button id="nfc-submit" type="submit" disabled>Sign in</button>
<p><a href="${url.loginRestartFlowUrl}">Start again</a> · Use Google or email from OakGate if card sign-in is unavailable.</p>
</form><script src="${url.resourcesPath}/js/oakgate-nfc.js" defer></script>
</#if></@layout.registrationLayout>
