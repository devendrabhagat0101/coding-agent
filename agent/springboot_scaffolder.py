"""
Spring Boot Microservice Scaffolder  (coding-agent v2.1.1)

Generates a complete, production-ready Spring Boot project structure using
pre-built templates — no LLM call required for the scaffold skeleton.
The LLM is used afterwards to generate domain-specific business logic.

Scaffold output:
  {service-name}/
  ├── build.gradle  (or pom.xml)
  ├── settings.gradle
  ├── gradle/wrapper/gradle-wrapper.properties
  ├── Dockerfile
  ├── docker-compose.yml          (if --docker)
  ├── Makefile
  ├── .gitignore
  └── src/
      ├── main/java/{package}/
      │   ├── {Name}Application.java
      │   ├── config/OpenApiConfig.java  (if --swagger)
      │   ├── controller/HealthController.java
      │   ├── exception/
      │   │   ├── ApiException.java
      │   │   └── GlobalExceptionHandler.java
      │   └── dto/ApiResponse.java
      ├── main/resources/
      │   └── application.yml
      └── test/java/{package}/
          └── {Name}ApplicationTests.java

Usage (via CLI):
    coding-agent springboot payment-service --port 8081 --db h2 --swagger
    coding-agent springboot order-service   --port 8082 --db postgres --docker
    coding-agent springboot auth-service    --port 8083 --db mysql --maven
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ── Spring Boot version matrix ─────────────────────────────────────────────────
SPRING_BOOT_VERSION    = "3.3.5"
SPRING_DEP_MGMT        = "1.1.6"
JAVA_VERSION           = "21"
GRADLE_VERSION         = "8.8"
SPRINGDOC_VERSION      = "2.6.0"


# ═══════════════════════════════════════════════════════════════════════════════
# Config dataclass
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SpringBootConfig:
    service_name: str                               # e.g. "payment-service"
    port: int           = 8080
    package: str        = ""                        # auto-derived if empty
    build_tool: str     = "gradle"                  # "gradle" | "maven"
    db: str             = "h2"                      # "none" | "h2" | "postgres" | "mysql"
    add_swagger: bool   = True
    add_docker: bool    = True
    output_dir: Path    = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if not self.package:
            safe = self.service_name.replace("-", "").replace("_", "").lower()
            self.package = f"com.dev2.{safe}"
        self.output_dir = Path(self.output_dir)

    @property
    def class_name(self) -> str:
        """payment-service → PaymentServiceApplication"""
        return (
            "".join(w.capitalize() for w in self.service_name.replace("-", "_").split("_"))
            + "Application"
        )

    @property
    def short_name(self) -> str:
        """payment-service → PaymentService"""
        return "".join(w.capitalize() for w in self.service_name.replace("-", "_").split("_"))

    @property
    def package_path(self) -> str:
        return self.package.replace(".", "/")

    @property
    def artifact_id(self) -> str:
        return self.service_name

    @property
    def group_id(self) -> str:
        parts = self.package.split(".")
        return ".".join(parts[:-1]) if len(parts) > 1 else self.package

    @property
    def project_root(self) -> Path:
        return self.output_dir / self.service_name


# ═══════════════════════════════════════════════════════════════════════════════
# Template generators
# ═══════════════════════════════════════════════════════════════════════════════

def _build_gradle(cfg: SpringBootConfig) -> str:
    # Build the deps list as properly indented lines
    deps: list[str] = [
        "implementation 'org.springframework.boot:spring-boot-starter-web'",
        "implementation 'org.springframework.boot:spring-boot-starter-actuator'",
        "implementation 'org.springframework.boot:spring-boot-starter-validation'",
    ]
    if cfg.add_swagger:
        deps.append(f"implementation 'org.springdoc:springdoc-openapi-starter-webmvc-ui:{SPRINGDOC_VERSION}'")
    if cfg.db in ("h2", "postgres", "mysql"):
        deps.append("implementation 'org.springframework.boot:spring-boot-starter-data-jpa'")
    if cfg.db == "h2":
        deps.append("runtimeOnly 'com.h2database:h2'")
    elif cfg.db == "postgres":
        deps.append("runtimeOnly 'org.postgresql:postgresql'")
    elif cfg.db == "mysql":
        deps.append("runtimeOnly 'com.mysql:mysql-connector-j'")
    deps += [
        "testImplementation 'org.springframework.boot:spring-boot-starter-test'",
        "testRuntimeOnly 'org.junit.platform:junit-platform-launcher'",
    ]
    indent = "    "
    deps_block = f"\n{indent}".join(deps)

    return (
        f"plugins {{\n"
        f"    id 'java'\n"
        f"    id 'org.springframework.boot' version '{SPRING_BOOT_VERSION}'\n"
        f"    id 'io.spring.dependency-management' version '{SPRING_DEP_MGMT}'\n"
        f"}}\n"
        f"\n"
        f"group = '{cfg.group_id}'\n"
        f"version = '1.0.0-SNAPSHOT'\n"
        f"\n"
        f"java {{\n"
        f"    toolchain {{\n"
        f"        languageVersion = JavaLanguageVersion.of({JAVA_VERSION})\n"
        f"    }}\n"
        f"}}\n"
        f"\n"
        f"repositories {{\n"
        f"    mavenCentral()\n"
        f"}}\n"
        f"\n"
        f"dependencies {{\n"
        f"    {deps_block}\n"
        f"}}\n"
        f"\n"
        f"tasks.named('test') {{\n"
        f"    useJUnitPlatform()\n"
        f"}}\n"
    )



def _settings_gradle(cfg: SpringBootConfig) -> str:
    return f"rootProject.name = '{cfg.service_name}'\n"


def _gradle_wrapper_properties() -> str:
    return textwrap.dedent(f"""\
        distributionBase=GRADLE_USER_HOME
        distributionPath=wrapper/dists
        distributionUrl=https\\://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip
        networkTimeout=10000
        validateDistributionUrl=true
        zipStoreBase=GRADLE_USER_HOME
        zipStorePath=wrapper/dists
    """)


def _pom_xml(cfg: SpringBootConfig) -> str:
    db_deps = _maven_db_deps(cfg.db)
    swagger_dep = (
        f"""
        <dependency>
            <groupId>org.springdoc</groupId>
            <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
            <version>{SPRINGDOC_VERSION}</version>
        </dependency>"""
        if cfg.add_swagger else ""
    )
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
                 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>

            <parent>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter-parent</artifactId>
                <version>{SPRING_BOOT_VERSION}</version>
                <relativePath/>
            </parent>

            <groupId>{cfg.group_id}</groupId>
            <artifactId>{cfg.artifact_id}</artifactId>
            <version>1.0.0-SNAPSHOT</version>
            <name>{cfg.service_name}</name>
            <description>{cfg.short_name} microservice</description>

            <properties>
                <java.version>{JAVA_VERSION}</java.version>
            </properties>

            <dependencies>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-web</artifactId>
                </dependency>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-actuator</artifactId>
                </dependency>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-validation</artifactId>
                </dependency>{swagger_dep}{db_deps}
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-test</artifactId>
                    <scope>test</scope>
                </dependency>
            </dependencies>

            <build>
                <plugins>
                    <plugin>
                        <groupId>org.springframework.boot</groupId>
                        <artifactId>spring-boot-maven-plugin</artifactId>
                    </plugin>
                </plugins>
            </build>
        </project>
    """)


def _maven_db_deps(db: str) -> str:
    if db == "h2":
        return """
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-data-jpa</artifactId>
                </dependency>
                <dependency>
                    <groupId>com.h2database</groupId>
                    <artifactId>h2</artifactId>
                    <scope>runtime</scope>
                </dependency>"""
    if db == "postgres":
        return """
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-data-jpa</artifactId>
                </dependency>
                <dependency>
                    <groupId>org.postgresql</groupId>
                    <artifactId>postgresql</artifactId>
                    <scope>runtime</scope>
                </dependency>"""
    if db == "mysql":
        return """
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-starter-data-jpa</artifactId>
                </dependency>
                <dependency>
                    <groupId>com.mysql</groupId>
                    <artifactId>mysql-connector-j</artifactId>
                    <scope>runtime</scope>
                </dependency>"""
    return ""


def _application_java(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package};

        import org.springframework.boot.SpringApplication;
        import org.springframework.boot.autoconfigure.SpringBootApplication;

        @SpringBootApplication
        public class {cfg.class_name} {{

            public static void main(String[] args) {{
                SpringApplication.run({cfg.class_name}.class, args);
            }}
        }}
    """)


def _application_yml(cfg: SpringBootConfig) -> str:
    db_block = _yml_db_config(cfg.db, cfg.service_name)
    swagger_block = (
        "springdoc:\n"
        "  api-docs:\n"
        "    path: /api-docs\n"
        "  swagger-ui:\n"
        "    path: /swagger-ui.html\n\n"
        if cfg.add_swagger else ""
    )
    # db_block lines are already indented under spring: (2 spaces)
    spring_db = f"\n{db_block}" if db_block else ""
    return (
        f"server:\n"
        f"  port: {cfg.port}\n"
        f"\n"
        f"spring:\n"
        f"  application:\n"
        f"    name: {cfg.service_name}\n"
        f"{spring_db}\n"
        f"management:\n"
        f"  endpoints:\n"
        f"    web:\n"
        f"      exposure:\n"
        f"        include: health,info,metrics\n"
        f"  endpoint:\n"
        f"    health:\n"
        f"      show-details: always\n"
        f"\n"
        f"{swagger_block}"
        f"logging:\n"
        f"  level:\n"
        f"    {cfg.package}: DEBUG\n"
        f"    org.springframework.web: INFO\n"
    )


def _yml_db_config(db: str, service_name: str) -> str:
    """Returns YAML lines that go inside `spring:` block (indented 2 spaces)."""
    db_name = service_name.replace("-", "_")
    if db == "h2":
        return (
            f"  datasource:\n"
            f"    url: jdbc:h2:mem:{db_name};DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE\n"
            f"    driver-class-name: org.h2.Driver\n"
            f"    username: sa\n"
            f"    password:\n"
            f"  h2:\n"
            f"    console:\n"
            f"      enabled: true\n"
            f"      path: /h2-console\n"
            f"  jpa:\n"
            f"    database-platform: org.hibernate.dialect.H2Dialect\n"
            f"    hibernate:\n"
            f"      ddl-auto: create-drop\n"
            f"    show-sql: false"
        )
    if db == "postgres":
        return (
            f"  datasource:\n"
            f"    url: jdbc:postgresql://localhost:5432/${{spring.application.name}}\n"
            f"    username: ${{DB_USER:postgres}}\n"
            f"    password: ${{DB_PASS:postgres}}\n"
            f"  jpa:\n"
            f"    database-platform: org.hibernate.dialect.PostgreSQLDialect\n"
            f"    hibernate:\n"
            f"      ddl-auto: update\n"
            f"    show-sql: false"
        )
    if db == "mysql":
        return (
            f"  datasource:\n"
            f"    url: jdbc:mysql://localhost:3306/${{spring.application.name}}?useSSL=false&serverTimezone=UTC\n"
            f"    username: ${{DB_USER:root}}\n"
            f"    password: ${{DB_PASS:root}}\n"
            f"  jpa:\n"
            f"    database-platform: org.hibernate.dialect.MySQLDialect\n"
            f"    hibernate:\n"
            f"      ddl-auto: update\n"
            f"    show-sql: false"
        )
    return ""


def _health_controller(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package}.controller;

        import org.springframework.http.ResponseEntity;
        import org.springframework.web.bind.annotation.GetMapping;
        import org.springframework.web.bind.annotation.RequestMapping;
        import org.springframework.web.bind.annotation.RestController;

        import {cfg.package}.dto.ApiResponse;

        import java.time.Instant;
        import java.util.Map;

        @RestController
        @RequestMapping("/api")
        public class HealthController {{

            @GetMapping("/health")
            public ResponseEntity<ApiResponse<Map<String, Object>>> health() {{
                return ResponseEntity.ok(ApiResponse.success(Map.of(
                    "service", "{cfg.service_name}",
                    "status", "UP",
                    "timestamp", Instant.now().toString()
                )));
            }}

            @GetMapping("/info")
            public ResponseEntity<ApiResponse<Map<String, String>>> info() {{
                return ResponseEntity.ok(ApiResponse.success(Map.of(
                    "name", "{cfg.service_name}",
                    "version", "1.0.0"
                )));
            }}
        }}
    """)


def _api_response_dto(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package}.dto;

        import com.fasterxml.jackson.annotation.JsonInclude;

        import java.time.Instant;

        @JsonInclude(JsonInclude.Include.NON_NULL)
        public record ApiResponse<T>(
                boolean success,
                String message,
                T data,
                String timestamp
        ) {{
            public static <T> ApiResponse<T> success(T data) {{
                return new ApiResponse<>(true, "OK", data, Instant.now().toString());
            }}

            public static <T> ApiResponse<T> success(String message, T data) {{
                return new ApiResponse<>(true, message, data, Instant.now().toString());
            }}

            public static <T> ApiResponse<T> error(String message) {{
                return new ApiResponse<>(false, message, null, Instant.now().toString());
            }}
        }}
    """)


def _api_exception(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package}.exception;

        import org.springframework.http.HttpStatus;

        public class ApiException extends RuntimeException {{

            private final HttpStatus status;

            public ApiException(HttpStatus status, String message) {{
                super(message);
                this.status = status;
            }}

            public ApiException(String message) {{
                this(HttpStatus.BAD_REQUEST, message);
            }}

            public HttpStatus getStatus() {{
                return status;
            }}
        }}
    """)


def _global_exception_handler(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package}.exception;

        import {cfg.package}.dto.ApiResponse;
        import org.slf4j.Logger;
        import org.slf4j.LoggerFactory;
        import org.springframework.http.HttpStatus;
        import org.springframework.http.ResponseEntity;
        import org.springframework.validation.FieldError;
        import org.springframework.web.bind.MethodArgumentNotValidException;
        import org.springframework.web.bind.annotation.ExceptionHandler;
        import org.springframework.web.bind.annotation.RestControllerAdvice;

        import java.util.HashMap;
        import java.util.Map;

        @RestControllerAdvice
        public class GlobalExceptionHandler {{

            private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

            @ExceptionHandler(ApiException.class)
            public ResponseEntity<ApiResponse<Void>> handleApiException(ApiException ex) {{
                log.warn("ApiException: {{}} — {{}}", ex.getStatus(), ex.getMessage());
                return ResponseEntity.status(ex.getStatus())
                        .body(ApiResponse.error(ex.getMessage()));
            }}

            @ExceptionHandler(MethodArgumentNotValidException.class)
            public ResponseEntity<ApiResponse<Map<String, String>>> handleValidation(
                    MethodArgumentNotValidException ex) {{
                Map<String, String> errors = new HashMap<>();
                ex.getBindingResult().getAllErrors().forEach(err -> {{
                    String field = err instanceof FieldError fe ? fe.getField() : err.getObjectName();
                    errors.put(field, err.getDefaultMessage());
                }});
                return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                        .body(ApiResponse.success("Validation failed", errors));
            }}

            @ExceptionHandler(Exception.class)
            public ResponseEntity<ApiResponse<Void>> handleGeneric(Exception ex) {{
                log.error("Unhandled exception", ex);
                return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                        .body(ApiResponse.error("Internal server error"));
            }}
        }}
    """)


def _openapi_config(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package}.config;

        import io.swagger.v3.oas.models.OpenAPI;
        import io.swagger.v3.oas.models.info.Info;
        import io.swagger.v3.oas.models.info.Contact;
        import org.springframework.context.annotation.Bean;
        import org.springframework.context.annotation.Configuration;

        @Configuration
        public class OpenApiConfig {{

            @Bean
            public OpenAPI openAPI() {{
                return new OpenAPI()
                        .info(new Info()
                                .title("{cfg.short_name} API")
                                .description("{cfg.short_name} microservice REST API")
                                .version("1.0.0")
                                .contact(new Contact()
                                        .name("Dev 2.0")
                                        .email("dev@dev2.com")));
            }}
        }}
    """)


def _application_tests(cfg: SpringBootConfig) -> str:
    return textwrap.dedent(f"""\
        package {cfg.package};

        import org.junit.jupiter.api.Test;
        import org.springframework.boot.test.context.SpringBootTest;

        @SpringBootTest
        class {cfg.class_name}Tests {{

            @Test
            void contextLoads() {{
            }}
        }}
    """)


def _dockerfile(cfg: SpringBootConfig) -> str:
    build_cmd = (
        "./gradlew bootJar -x test"
        if cfg.build_tool == "gradle"
        else "./mvnw package -DskipTests"
    )
    jar_glob = (
        f"build/libs/{cfg.service_name}-*.jar"
        if cfg.build_tool == "gradle"
        else f"target/{cfg.service_name}-*.jar"
    )
    return textwrap.dedent(f"""\
        # ── Build stage ───────────────────────────────────────────────────────────
        FROM eclipse-temurin:{JAVA_VERSION}-jdk AS builder
        WORKDIR /app
        COPY . .
        RUN {build_cmd}

        # ── Runtime stage ─────────────────────────────────────────────────────────
        FROM eclipse-temurin:{JAVA_VERSION}-jre AS runtime
        WORKDIR /app

        RUN addgroup --system spring && adduser --system --ingroup spring spring
        USER spring:spring

        COPY --from=builder /app/{jar_glob} app.jar

        EXPOSE {cfg.port}
        ENTRYPOINT ["java", "-jar", "app.jar"]
    """)


def _docker_compose(cfg: SpringBootConfig) -> str:
    db_service = _compose_db_service(cfg.db, cfg.service_name)
    depends_on  = "\n      depends_on:\n        - db" if db_service else ""
    env_vars    = _compose_env_vars(cfg.db)
    return textwrap.dedent(f"""\
        services:
          {cfg.service_name}:
            build: .
            ports:
              - "{cfg.port}:{cfg.port}"
            environment:
              - SPRING_PROFILES_ACTIVE=docker{env_vars}{depends_on}
            restart: unless-stopped
        {db_service}
    """)


def _compose_db_service(db: str, service_name: str) -> str:
    db_name = service_name.replace("-", "_")
    if db == "postgres":
        return textwrap.dedent(f"""
          db:
            image: postgres:16-alpine
            environment:
              POSTGRES_DB: {db_name}
              POSTGRES_USER: postgres
              POSTGRES_PASSWORD: postgres
            ports:
              - "5432:5432"
            volumes:
              - postgres_data:/var/lib/postgresql/data

        volumes:
          postgres_data:""")
    if db == "mysql":
        return textwrap.dedent(f"""
          db:
            image: mysql:8
            environment:
              MYSQL_DATABASE: {db_name}
              MYSQL_ROOT_PASSWORD: root
            ports:
              - "3306:3306"
            volumes:
              - mysql_data:/var/lib/mysql

        volumes:
          mysql_data:""")
    return ""


def _compose_env_vars(db: str) -> str:
    if db == "postgres":
        return "\n              - DB_USER=postgres\n              - DB_PASS=postgres"
    if db == "mysql":
        return "\n              - DB_USER=root\n              - DB_PASS=root"
    return ""


def _makefile(cfg: SpringBootConfig) -> str:
    if cfg.build_tool == "gradle":
        return textwrap.dedent(f"""\
            .PHONY: setup build test run docker-build docker-up docker-down clean

            setup:
            \tgradle wrapper --gradle-version={GRADLE_VERSION}
            \tchmod +x gradlew

            build:
            \t./gradlew build

            test:
            \t./gradlew test

            run:
            \t./gradlew bootRun

            jar:
            \t./gradlew bootJar -x test

            docker-build:
            \tdocker build -t {cfg.service_name}:latest .

            docker-up:
            \tdocker-compose up -d

            docker-down:
            \tdocker-compose down

            clean:
            \t./gradlew clean
        """)
    else:
        return textwrap.dedent(f"""\
            .PHONY: build test run docker-build docker-up docker-down clean

            build:
            \t./mvnw package

            test:
            \t./mvnw test

            run:
            \t./mvnw spring-boot:run

            jar:
            \t./mvnw package -DskipTests

            docker-build:
            \tdocker build -t {cfg.service_name}:latest .

            docker-up:
            \tdocker-compose up -d

            docker-down:
            \tdocker-compose down

            clean:
            \t./mvnw clean
        """)


def _gitignore() -> str:
    return textwrap.dedent("""\
        # Build
        build/
        target/
        out/
        .gradle/
        *.jar
        !gradle/wrapper/gradle-wrapper.jar

        # IDE
        .idea/
        .vscode/
        *.iml
        *.iws

        # OS
        .DS_Store
        Thumbs.db

        # Env
        .env
        .env.local
        application-secret.yml

        # Logs
        *.log
        logs/
    """)


def _readme(cfg: SpringBootConfig) -> str:
    swagger_note = (
        f"\n- **Swagger UI**: http://localhost:{cfg.port}/swagger-ui.html"
        f"\n- **API Docs**: http://localhost:{cfg.port}/api-docs"
        if cfg.add_swagger else ""
    )
    gradle_note = (
        "\n> **First time only:** Run `make setup` (or `gradle wrapper`) to generate the Gradle wrapper.\n"
        if cfg.build_tool == "gradle" else ""
    )
    return textwrap.dedent(f"""\
        # {cfg.short_name}

        Spring Boot {SPRING_BOOT_VERSION} microservice — {cfg.service_name}

        ## Quick start
        {gradle_note}
        ```bash
        make run          # start on port {cfg.port}
        make test         # run tests
        make docker-up    # start with Docker Compose
        ```

        ## Endpoints

        | Method | Path | Description |
        |--------|------|-------------|
        | GET | `/api/health` | Health check |
        | GET | `/api/info` | Service info |
        | GET | `/actuator/health` | Spring Actuator health |
        {swagger_note}

        ## Configuration

        Key properties in `src/main/resources/application.yml`:

        | Property | Default | Description |
        |----------|---------|-------------|
        | `server.port` | `{cfg.port}` | HTTP port |
        | `spring.application.name` | `{cfg.service_name}` | Service name |

        ## Project structure

        ```
        src/main/java/{cfg.package_path}/
        ├── {cfg.class_name}.java          ← entry point
        ├── config/                         ← Spring configuration
        ├── controller/                     ← REST controllers
        ├── service/                        ← business logic
        ├── repository/                     ← data access
        ├── model/                          ← JPA entities
        ├── dto/                            ← request/response records
        └── exception/                      ← error handling
        ```

        Generated by [coding-agent](https://github.com/dev2/coding-agent)
    """)


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def scaffold_spring_boot(cfg: SpringBootConfig) -> list[Path]:
    """
    Write all scaffold files to disk.
    Returns a list of written file paths.
    """
    root = cfg.project_root
    root.mkdir(parents=True, exist_ok=True)

    java_root = root / "src" / "main" / "java" / cfg.package_path
    test_root  = root / "src" / "test" / "java" / cfg.package_path
    res_root   = root / "src" / "main" / "resources"

    written: list[tuple[str, str]] = []

    # ── Build files ───────────────────────────────────────────────────────────
    if cfg.build_tool == "gradle":
        written += [
            ("build.gradle",                            _build_gradle(cfg)),
            ("settings.gradle",                         _settings_gradle(cfg)),
            ("gradle/wrapper/gradle-wrapper.properties", _gradle_wrapper_properties()),
        ]
    else:
        written += [
            ("pom.xml", _pom_xml(cfg)),
        ]

    # ── Application entry point ───────────────────────────────────────────────
    written.append((
        f"src/main/java/{cfg.package_path}/{cfg.class_name}.java",
        _application_java(cfg),
    ))

    # ── Resources ─────────────────────────────────────────────────────────────
    written.append(("src/main/resources/application.yml", _application_yml(cfg)))

    # ── Controller ────────────────────────────────────────────────────────────
    written.append((
        f"src/main/java/{cfg.package_path}/controller/HealthController.java",
        _health_controller(cfg),
    ))

    # ── DTO ───────────────────────────────────────────────────────────────────
    written.append((
        f"src/main/java/{cfg.package_path}/dto/ApiResponse.java",
        _api_response_dto(cfg),
    ))

    # ── Exception handling ────────────────────────────────────────────────────
    written += [
        (f"src/main/java/{cfg.package_path}/exception/ApiException.java",        _api_exception(cfg)),
        (f"src/main/java/{cfg.package_path}/exception/GlobalExceptionHandler.java", _global_exception_handler(cfg)),
    ]

    # ── Swagger / OpenAPI ─────────────────────────────────────────────────────
    if cfg.add_swagger:
        written.append((
            f"src/main/java/{cfg.package_path}/config/OpenApiConfig.java",
            _openapi_config(cfg),
        ))

    # ── Empty placeholder dirs ────────────────────────────────────────────────
    for sub in ("service", "repository", "model"):
        placeholder = f"src/main/java/{cfg.package_path}/{sub}/.gitkeep"
        written.append((placeholder, ""))

    # ── Tests ─────────────────────────────────────────────────────────────────
    written.append((
        f"src/test/java/{cfg.package_path}/{cfg.class_name}Tests.java",
        _application_tests(cfg),
    ))

    # ── Docker ────────────────────────────────────────────────────────────────
    written.append(("Dockerfile", _dockerfile(cfg)))
    if cfg.add_docker:
        written.append(("docker-compose.yml", _docker_compose(cfg)))

    # ── Misc ──────────────────────────────────────────────────────────────────
    written += [
        ("Makefile",    _makefile(cfg)),
        (".gitignore",  _gitignore()),
        ("README.md",   _readme(cfg)),
    ]

    # ── Write all files ───────────────────────────────────────────────────────
    paths: list[Path] = []
    for rel, content in written:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        paths.append(target)
        console.print(f"  [green]✓[/] {rel}")

    return paths


# ═══════════════════════════════════════════════════════════════════════════════
# Display helpers
# ═══════════════════════════════════════════════════════════════════════════════

def print_scaffold_plan(cfg: SpringBootConfig) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key",   style="dim")
    table.add_column("Value", style="cyan")
    table.add_row("Service",    cfg.service_name)
    table.add_row("Package",    cfg.package)
    table.add_row("Port",       str(cfg.port))
    table.add_row("Build",      cfg.build_tool)
    table.add_row("Database",   cfg.db)
    table.add_row("Swagger",    "yes" if cfg.add_swagger else "no")
    table.add_row("Docker",     "yes" if cfg.add_docker  else "no")
    table.add_row("Output",     str(cfg.output_dir / cfg.service_name))
    console.print(
        Panel(table, title="[bold green]Spring Boot Scaffold Plan[/]", expand=False)
    )


def print_scaffold_summary(cfg: SpringBootConfig, file_count: int) -> None:
    build_tool_run = (
        "make setup && make run   # (make setup generates the Gradle wrapper — first time only)"
        if cfg.build_tool == "gradle"
        else "make run"
    )
    console.print(
        Panel(
            f"[bold green]✓ Scaffold complete![/]  {file_count} files written.\n\n"
            f"  [dim]Location:[/]  [cyan]{cfg.project_root}[/]\n\n"
            f"  [dim]Next steps:[/]\n"
            f"    cd {cfg.service_name}\n"
            f"    {build_tool_run}\n\n"
            f"  [dim]Add your business logic to:[/]\n"
            f"    src/main/java/{cfg.package_path}/service/\n"
            f"    src/main/java/{cfg.package_path}/controller/\n"
            f"    src/main/java/{cfg.package_path}/model/\n\n"
            + (
                f"  [dim]Swagger UI:[/]  http://localhost:{cfg.port}/swagger-ui.html\n"
                if cfg.add_swagger else ""
            )
            + f"  [dim]Health:[/]      http://localhost:{cfg.port}/api/health",
            title=f"[bold]coding-agent — {cfg.service_name}[/]",
            expand=False,
        )
    )
