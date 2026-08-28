import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

plugins {
    application
    `java-library`
    kotlin("jvm") version "2.1.0"
}

repositories {
    google()
    mavenCentral()
}

// -----------------------------------------------------------------------------
// json2rc builds the androidx RemoteCompose core + creation-core straight from a
// local source checkout, so it always tracks whatever RemoteCompose you have on
// disk. When the upstream json2rc tool lands we can drop this and depend on the
// published artifacts instead.
//
// Override the checkout location with:  -PandroidxRemote=/path/to/compose/remote
// -----------------------------------------------------------------------------
val androidxRemote =
    (findProperty("androidxRemote") as String?)
        ?: "/Users/nico/androidx/frameworks/support/compose/remote"

val patchedUpstream = layout.buildDirectory.dir("patched-upstream").get().asFile

val mirrorUpstream = tasks.register<Sync>("mirrorUpstream") {
    description = "Mirror androidx remote-core + remote-creation-core main sources."
    from("$androidxRemote/remote-core/src/main/java")
    from("$androidxRemote/remote-creation-core/src/main/java")
    into(patchedUpstream)
}

sourceSets {
    main {
        java.srcDir(patchedUpstream)
    }
}

kotlin {
    sourceSets.main {
        kotlin.srcDir(patchedUpstream)
    }
}

tasks.withType<JavaCompile>().configureEach { dependsOn(mirrorUpstream) }
tasks.withType<KotlinCompile>().configureEach { dependsOn(mirrorUpstream) }

dependencies {
    implementation("org.jspecify:jspecify:1.0.0")
    implementation("androidx.annotation:annotation-jvm:1.9.1")
    implementation("org.jetbrains.kotlin:kotlin-stdlib")
    implementation("org.json:json:20231013")
}

application {
    applicationName = "json2rc"
    mainClass.set("refract.json2rc.Main")
}

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(21)) }
}
