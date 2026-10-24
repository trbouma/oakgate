FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /build
COPY keycloak/nfc/pom.xml ./pom.xml
COPY keycloak/nfc/src ./src
RUN mvn -B -ntp package
FROM quay.io/keycloak/keycloak:26.8.0
COPY --from=build --chown=keycloak:keycloak /build/target/oakgate-nfc-0.1.0.jar /opt/keycloak/providers/oakgate-nfc.jar
