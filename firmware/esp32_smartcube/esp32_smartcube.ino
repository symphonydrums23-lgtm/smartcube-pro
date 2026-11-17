#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- CONFIGURA AQUI ---
const char* WIFI_SSID = "NOME_DO_WIFI_DO_CONDOMINIO";
const char* WIFI_PASS = "SENHA_DO_WIFI";
const char* API_BASE = "https://SEU-BACKEND.onrender.com/api";
const char* TABLET_TOKEN = "COLA_AQUI_O_X-TABLET-TOKEN";
const char* CONDOMINIO_ID = "1";

#define PINO_TRAVA 2

unsigned long abertoAte = 0;
bool travaAberta = false;
int boxAberto = 0;
char ladoAberto = 'F';

void setup() {
  Serial.begin(115200);
  pinMode(PINO_TRAVA, OUTPUT);
  digitalWrite(PINO_TRAVA, LOW);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
}

void abrirTrava(int box, char lado) {
  Serial.println("ABERTO:" + String(box) + ":" + String(lado));
  digitalWrite(PINO_TRAVA, HIGH);
  travaAberta = true;
  boxAberto = box;
  ladoAberto = lado;
  abertoAte = millis() + 15000; // timeout 15s - já tinha, mantido
}

void fecharTrava(int box, char lado) {
  Serial.println("FECHADO:" + String(box) + ":" + String(lado));
  digitalWrite(PINO_TRAVA, LOW);
  travaAberta = false;
}

void confirmarAbertura(String nonce, String comando_id) {
  HTTPClient http;
  http.begin(String(API_BASE) + "/tablet/porta-evento");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Tablet-Token", TABLET_TOKEN);
  String body = "{\"evento\":\"aberta\",\"nonce\":\"" + nonce + "\",\"comando_id\":\"" + comando_id + "\",\"condominio_id\":\"" + String(CONDOMINIO_ID) + "\"}";
  int code = http.POST(body);
  Serial.println("Confirmar: " + String(code));
  http.end();
}

void pollPorta() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(String(API_BASE) + "/tablet/poll");
  http.addHeader("X-Tablet-Token", TABLET_TOKEN);
  int code = http.GET();
  if (code != 200) { http.end(); return; }

  String payload = http.getString();
  http.end();

  DynamicJsonDocument doc(1024);
  if (deserializeJson(doc, payload)) return;

  if (doc["abrir"] == true) {
    int box = doc["box"] | 1;
    String ladoStr = doc["lado"] | "F";
    char lado = ladoStr.charAt(0);
    String nonce = doc["nonce"] | "";
    String comando_id = doc["comando_id"] | doc["id"] | "";

    abrirTrava(box, lado);
    confirmarAbertura(nonce, comando_id);
  }
}

void loop() {
  // Timeout 15s - segurança
  if (travaAberta && millis() > abertoAte) {
    fecharTrava(boxAberto, ladoAberto);
  }

  // Mantido: abre por Serial pra teste na bancada
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("OPEN:")) {
      int box = cmd.substring(5, 7).toInt();
      char lado = cmd.charAt(8);
      abrirTrava(box, lado);
    }
  }

  // NOVO: poll a cada 2s
  static unsigned long ultimoPoll = 0;
  if (millis() - ultimoPoll > 2000) {
    ultimoPoll = millis();
    pollPorta();
  }
  delay(100);
}
