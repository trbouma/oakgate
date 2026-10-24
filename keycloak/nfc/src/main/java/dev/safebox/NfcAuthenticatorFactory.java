package dev.safebox;
import java.util.List;
import org.keycloak.Config;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.AuthenticatorFactory;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderConfigProperty;
public final class NfcAuthenticatorFactory implements AuthenticatorFactory {
 public String getId() { return "oakgate-nfc-pin"; }
 public String getDisplayType() { return "OakGate NFC card and PIN"; }
 public String getReferenceCategory() { return "oakgate-nfc"; }
 public String getHelpText() { return "Dedicated OakGate NFC client only; verifies an enrolled card and PIN with OakGate."; }
 public boolean isConfigurable() { return false; }
 public boolean isUserSetupAllowed() { return false; }
 public List<ProviderConfigProperty> getConfigProperties() { return List.of(); }
 public AuthenticationExecutionModel.Requirement[] getRequirementChoices() { return new AuthenticationExecutionModel.Requirement[]{AuthenticationExecutionModel.Requirement.REQUIRED, AuthenticationExecutionModel.Requirement.DISABLED}; }
 public Authenticator create(KeycloakSession s) { return new NfcAuthenticator(); }
 public void init(Config.Scope c) { }
 public void postInit(KeycloakSessionFactory f) { }
 public void close() { }
}
