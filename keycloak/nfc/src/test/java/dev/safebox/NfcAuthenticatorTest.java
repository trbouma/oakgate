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
    @Test void credentialRequestUsesHttp11AndKeepsJsonBody() throws Exception {
      var c=context(); var http=transport("{}",401);
      new NfcAuthenticator(env::get,http).action(c);
      var captor=org.mockito.ArgumentCaptor.forClass(HttpRequest.class);
      verify(http).send(captor.capture(),any(HttpResponse.BodyHandler.class));
      var request=captor.getValue();
      assertEquals(HttpClient.Version.HTTP_1_1,request.version().orElseThrow());
      assertEquals("application/json",request.headers().firstValue("Content-Type").orElseThrow());
      // Exercise real Java HTTP framing, not only a mock's serialized response.
      var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
      var received=new java.util.concurrent.CompletableFuture<String>();
      server.createContext("/verify",exchange -> {
        String body=new String(exchange.getRequestBody().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        if (exchange.getRequestHeaders().getFirst("Upgrade") != null) received.completeExceptionally(new AssertionError("Unexpected h2c upgrade"));
        else received.complete(body);
        exchange.sendResponseHeaders(204,-1); exchange.close();
      });
      server.start();
      try (var client=HttpClient.newHttpClient()) {
        var actual=HttpRequest.newBuilder(java.net.URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/verify"))
          .version(request.version().orElseThrow()).timeout(java.time.Duration.ofSeconds(3))
          .header("Content-Type","application/json").POST(request.bodyPublisher().orElseThrow()).build();
        assertEquals(204,client.send(actual,HttpResponse.BodyHandlers.discarding()).statusCode());
        Map<?,?> body=org.keycloak.util.JsonSerialization.readValue(received.get(3,java.util.concurrent.TimeUnit.SECONDS),Map.class);
        assertEquals("opaque",body.get("card")); assertEquals("0123",body.get("pin"));
        assertEquals(nonce,body.get("nonce")); assertEquals("oakgate-nfc",body.get("client_id"));
      } finally { server.stop(0); }
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
