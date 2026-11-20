#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ===== CONFIG - TROCA AQUI =====
const char* WIFI_SSID = "SEU_WIFI";
const char* WIFI_PASS = "SUA_SENHA";
const char* ESP32_TOKEN = "SC-ESP32-9f8K2mQ7xP4vL1aZ8bN3cD6";
const char* CONDOMINIO_ID = "ID_DO_CONDOMINIO";
// ===============================

#define RELE_PIN 23
#define LED_PIN 2

unsigned long ultimoPoll = 0;
String nonceAtual = "";

void setup() {
  Serial.begin(115200);
  pinMode(RELE_PIN, OUTPUT);
  digitalWrite(RELE_PIN, LOW); // trava FECHADA
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
}

void abrirTrava(String box, String lado, String acao, String nonce) {
  Serial.println("ABRINDO Box " + box + " Lado " + lado + " Acao " + acao);

  digitalWrite(LED_PIN, HIGH);
  digitalWrite(RELE_PIN, HIGH); // abre trava
  delay(15000); // 15s aberto - tempo pra pegar encomenda
  digitalWrite(RELE_PIN, LOW); // fecha trava
  digitalWrite(LED_PIN, LOW);

  // Confirma pro backend que abriu de verdade
  confirmar(box, nonce, true);
}

void confirmar(String box, String nonce, bool abriu) {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/esp32/confirmar");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-ESP32-Token", ESP32_TOKEN);
  http.addHeader("x-condominio-id", CONDOMINIO_ID);

  StaticJsonDocument<512> doc;
  doc["nonce"] = nonce;
  doc["box"] = box;
  doc["porta_aberta"] = abriu;
  doc["sensor_abertura"] = abriu;
  doc["reed"] = abriu;

  String body;
  serializeJson(doc, body);
  int code = http.POST(body);
  Serial.println("Confirmar: " + String(code) + " " + http.getString());
  http.end();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(2000);
    return;
  }

  // Poll a cada 2s
  if (millis() - ultimoPoll < 2000) return;
  ultimoPoll = millis();

  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/esp32/poll");
  http.addHeader("X-ESP32-Token", ESP32_TOKEN);
  http.addHeader("x-condominio-id", CONDOMINIO_ID);

  int code = http.GET();
  if (code != 200) {
    Serial.println("Poll erro: " + String(code));
    http.end();
    return;
  }

  String payload = http.getString();
  http.end();

  StaticJsonDocument<2048> doc;
  if (deserializeJson(doc, payload)) return;

  JsonArray cmds = doc["comandos"];
  if (cmds.size() == 0) return;

  // Pega só o primeiro comando da fila
  JsonObject cmd = cmds[0];
  String nonce = cmd["nonce"].as<String>();
  String box = cmd["box"].as<String>();
  String lado = cmd["lado"].as<String>();
  String acao = cmd["acao"].as<String>();

  // Anti-replay local: não abre 2x o mesmo nonce
  if (nonce == nonceAtual) return;
  nonceAtual = nonce;

  abrirTrava(box, lado, acao, nonce);
}
