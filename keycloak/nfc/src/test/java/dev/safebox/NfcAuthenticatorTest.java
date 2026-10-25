package dev.safebox;
import java.net.http.*;
import java.util.*;
import jakarta.ws.rs.core.MultivaluedHashMap;
import org.junit.jupiter.api.Test;
import org.keycloak.authentication.*;
import org.keycloak.models.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class NfcAuthenticatorTest {
    private final String nonce = "a".repeat(64);
    private final Map<String,String> env = new HashMap<>(Map.of(
      "OAKGATE_NFC_LOGIN_ENABLED","true", "OAKGATE_OIDC_ISSUER","https://identity.example/realms/oakgate",
      "OAKGATE_NFC_CLIENT_ID","oakgate-nfc", "OAKGATE_NFC_BACKCHANNEL_SECRET","s".repeat(64),
      "OAKGATE_NFC_API_URL","http://app:8000/api/cards/v1/login/verify"));
    private AuthenticationFlowContext context() {
      var c = mock(AuthenticationFlowContext.class, RETURNS_DEEP_STUBS);
      when(c.getRealm().getName()).thenReturn("oakgate");
      when(c.getAuthenticationSession().getClient().getClientId()).thenReturn("oakgate-nfc");
      when(c.getAuthenticationSession().getAuthNote("oakgate.nfc.challenge")).thenReturn(nonce);
      when(c.getAuthenticationSession().getAuthNote("oakgate.nfc.challenge.time")).thenReturn(Long.toString(System.currentTimeMillis()));
      var fields = new MultivaluedHashMap<String,String>(); fields.putSingle("card","opaque"); fields.putSingle("pin","0123");
      when(c.getHttpRequest().getDecodedFormParameters()).thenReturn(fields);
      return c;
    }
    @SuppressWarnings("unchecked") private HttpClient transport(String body, int status) throws Exception {
      HttpClient http = mock(HttpClient.class);
      HttpResponse<String> response = mock(HttpResponse.class);
      when(response.statusCode()).thenReturn(status); when(response.body()).thenReturn(body);
      when(http.send(any(HttpRequest.class), any(HttpResponse.BodyHandler.class))).thenReturn(response);
      return http;
    }
    private String reply(String sub) { return "{\"sub\":\""+sub+"\",\"nonce\":\""+nonce+"\",\"issuer\":\"https://identity.example/realms/oakgate\"}"; }
    @Test void successUsesExistingIdOnly() throws Exception {
      var c=context(); var http=transport(reply("stable-id"),200);
      var user=mock(UserModel.class); when(user.isEnabled()).thenReturn(true);
      when(c.getSession().users().getUserById(c.getRealm(),"stable-id")).thenReturn(user);
      new NfcAuthenticator(env::get,http).action(c);
      verify(c).setUser(user); verify(c).success();
      verify(c.getAuthenticationSession()).removeAuthNote("oakgate.nfc.challenge");
      verify(http,times(1)).send(any(),any(HttpResponse.BodyHandler.class));
    }
    @Test void blankPinIsCheckedByBackendNotAssumedAuthorized() throws Exception {
      var c=context(); var http=transport("{}",401);
      c.getHttpRequest().getDecodedFormParameters().putSingle("pin", "");
      new NfcAuthenticator(env::get,http).action(c);
      verify(http,times(1)).send(any(),any(HttpResponse.BodyHandler.class));
      verify(c,never()).success();
    }
    @Test void disabledOrMissingUserCannotLogin() throws Exception {
      for (boolean missing : List.of(true,false)) {
        var c=context(); var http=transport(reply("stable-id"),200);
        UserModel user=missing?null:mock(UserModel.class);
        when(c.getSession().users().getUserById(c.getRealm(),"stable-id")).thenReturn(user);
        new NfcAuthenticator(env::get,http).action(c); verify(c,never()).success();
      }
    }
    @Test void badRepliesCannotLogin() throws Exception {
      for (String body : List.of(reply("stable-id").replace(nonce,"wrong"), "{}", reply("stable-id").replace("identity.example","evil.example"))) {
        var c=context(); new NfcAuthenticator(env::get,transport(body,200)).action(c);
        verify(c,never()).success();
      }
      var c=context(); new NfcAuthenticator(env::get,transport(reply("stable-id"),401)).action(c);
      verify(c,never()).success();
    }
    @Test void wrongClientAndExpiredChallengeNeverCallBackend() throws Exception {
      var c=context(); var http=mock(HttpClient.class);
      when(c.getAuthenticationSession().getClient().getClientId()).thenReturn("oakgate-web");
      new NfcAuthenticator(env::get,http).action(c); verifyNoInteractions(http); verify(c,never()).success();
      c=context(); when(c.getAuthenticationSession().getAuthNote("oakgate.nfc.challenge.time")).thenReturn("0");
      new NfcAuthenticator(env::get,http).action(c); verifyNoInteractions(http); verify(c,never()).success();
    }
    @Test void disabledAndInsecureRemoteFailClosed() throws Exception {
      var c=context(); var http=mock(HttpClient.class);
      env.put("OAKGATE_NFC_LOGIN_ENABLED","false");
      new NfcAuthenticator(env::get,http).action(c); verifyNoInteractions(http);
      env.put("OAKGATE_NFC_LOGIN_ENABLED","true"); env.put("OAKGATE_NFC_API_URL","http://external.example/api/cards/v1/login/verify");
      c=context(); new NfcAuthenticator(env::get,http).action(c); verifyNoInteractions(http); verify(c,never()).success();
    }
    @Test void timeoutDoesNotRetry() throws Exception {
      var c=context(); var http=mock(HttpClient.class);
      when(http.send(any(),any(HttpResponse.BodyHandler.class))).thenThrow(new java.net.http.HttpTimeoutException("test"));
      new NfcAuthenticator(env::get,http).action(c);
      verify(http,times(1)).send(any(),any(HttpResponse.BodyHandler.class)); verify(c,never()).success();
    }
}
