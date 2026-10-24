package dev.safebox;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import jakarta.ws.rs.core.Response;
import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.AuthenticationFlowError;
import org.keycloak.authentication.Authenticator;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.util.JsonSerialization;

/** Only for the dedicated oakgate-nfc client. Never creates or links users. */
public final class NfcAuthenticator implements Authenticator {
    private static final String NOTE = "oakgate.nfc.challenge";
    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(3)).followRedirects(HttpClient.Redirect.NEVER).build();
    private final java.util.function.Function<String,String> environment;
    private final HttpClient transport;
    public NfcAuthenticator() { this(System::getenv, HTTP); }
    NfcAuthenticator(java.util.function.Function<String,String> environment, HttpClient transport) {
        this.environment = environment; this.transport = transport;
    }
    private String env(String name) { return environment.apply(name); }
    private boolean allowed(AuthenticationFlowContext c) {
        String issuer = env("OAKGATE_OIDC_ISSUER");
        String client = env("OAKGATE_NFC_CLIENT_ID");
        String secret = env("OAKGATE_NFC_BACKCHANNEL_SECRET");
        return "true".equalsIgnoreCase(env("OAKGATE_NFC_LOGIN_ENABLED"))
            && issuer != null && issuer.endsWith("/realms/" + c.getRealm().getName())
            && client != null && client.equals(c.getAuthenticationSession().getClient().getClientId())
            && secret != null && secret.length() >= 32;
    }
    private void page(AuthenticationFlowContext c, boolean failed) {
        byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
        c.getAuthenticationSession().setAuthNote(NOTE, HexFormat.of().formatHex(bytes));
        c.getAuthenticationSession().setAuthNote(NOTE + ".time", Long.toString(System.currentTimeMillis()));
        var form = c.form();
        if (failed) form.setError("Card sign-in could not be verified. Use your usual sign-in if the card is locked or unavailable.");
        Response page = form.createForm("oakgate-nfc.ftl");
        if (failed) c.failureChallenge(AuthenticationFlowError.INVALID_CREDENTIALS, page);
        else c.challenge(page);
    }
    @Override public void authenticate(AuthenticationFlowContext c) {
        if (!allowed(c)) { c.failure(AuthenticationFlowError.ACCESS_DENIED); return; }
        page(c, false);
    }
    @Override public void action(AuthenticationFlowContext c) {
        if (!allowed(c)) { c.failure(AuthenticationFlowError.ACCESS_DENIED); return; }
        String nonce = c.getAuthenticationSession().getAuthNote(NOTE);
        String started = c.getAuthenticationSession().getAuthNote(NOTE + ".time");
        c.getAuthenticationSession().removeAuthNote(NOTE);
        c.getAuthenticationSession().removeAuthNote(NOTE + ".time");
        try {
            var fields = c.getHttpRequest().getDecodedFormParameters();
            String card = fields.getFirst("card"), pin = fields.getFirst("pin");
            if (nonce == null || started == null || System.currentTimeMillis()-Long.parseLong(started)>120000
                || card == null || card.length()>536 || pin == null || !pin.matches("[0-9]{4}")) {
                page(c, true); return;
            }
            URI endpoint = URI.create(env("OAKGATE_NFC_API_URL"));
            // HTTP is permitted only on this fixed Compose service hop. Remote hops require TLS.
            if (!("https".equals(endpoint.getScheme()) ||
                ("http".equals(endpoint.getScheme()) && "app".equals(endpoint.getHost()) && endpoint.getPort()==8000))
                || endpoint.getUserInfo()!=null || endpoint.getQuery()!=null || endpoint.getFragment()!=null
                || !"/api/cards/v1/login/verify".equals(endpoint.getPath())) throw new IllegalArgumentException();
            String issuer = env("OAKGATE_OIDC_ISSUER");
            String body = JsonSerialization.writeValueAsString(Map.of("card",card,"pin",pin,"nonce",nonce,
                "issuer",issuer,"client_id",env("OAKGATE_NFC_CLIENT_ID")));
            HttpRequest request = HttpRequest.newBuilder(endpoint).timeout(Duration.ofSeconds(8))
                .header("Authorization", "Bearer " + env("OAKGATE_NFC_BACKCHANNEL_SECRET"))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build();
            // Never retry credentials automatically after a timeout or ambiguous response.
            HttpResponse<String> response = transport.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode()!=200 || response.body().length()>2048) { page(c,true); return; }
            Map<?,?> result = JsonSerialization.readValue(response.body(), Map.class);
            if (!nonce.equals(result.get("nonce")) || !issuer.equals(result.get("issuer"))
                || !(result.get("sub") instanceof String sub)) { page(c,true); return; }
            UserModel user = c.getSession().users().getUserById(c.getRealm(), sub);
            if (user == null || !user.isEnabled()) { page(c,true); return; }
            c.setUser(user);
            c.success();
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt(); c.failure(AuthenticationFlowError.INTERNAL_ERROR);
        } catch (Exception ex) {
            // Do not log payloads, PINs, headers, response bodies or exception messages.
            page(c, true);
        }
    }
    @Override public boolean requiresUser() { return false; }
    @Override public boolean configuredFor(KeycloakSession s, RealmModel r, UserModel u) { return true; }
    @Override public void setRequiredActions(KeycloakSession s, RealmModel r, UserModel u) { }
    @Override public void close() { }
}
