FROM maven:3.9.9-eclipse-temurin-8 AS build
WORKDIR /app

COPY pom.xml .
COPY src ./src

RUN mvn -B clean package -DskipTests

FROM eclipse-temurin:8-jre
WORKDIR /app

COPY --from=build /app/target/Service_Monitor-0.0.1-SNAPSHOT.jar app.jar

EXPOSE 8081

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
