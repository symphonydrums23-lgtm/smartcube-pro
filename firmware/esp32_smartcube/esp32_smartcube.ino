#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_task_wdt.h>

// CORRIGIDO: NADA hardcoded aqui. Antes WIFI, senha, token e condominio_id estavam no código
// Quem pegava o .ino ou o binário tinha acesso total ao armário
// Configura 1x via Serial com SET: + grava em NVS (Preferences), depois apaga do código
// Exemplo via Serial: SET WIFI_SSID=Nome / SET WIFI_PASS=... / SET API_BASE=https://... / SET TOKEN=... / SET CONDOMINIO_ID=12
// Depois: SAVE e REBOOT

Preferences prefs;
String WIFI_SSID = "";
String WIFI_PASS = "";
String API_BASE = "";
String ESP32_TOKEN = "";
String CONDOMINIO_ID = "";

#define PINO_TRAVA 2
#define WDT_TIMEOUT 30 // segundos

unsigned long abertoAte = 0;
bool travaAberta = false;
int boxAberto = 0;
char ladoAberto = 'F';
String ultimoNonce = ""; // CORRIGIDO: anti-replay, antes mesmo nonce abria 100x

void carregarConfig() {
  prefs.begin("smartcube", true);
  WIFI_SSID = prefs.getString("ssid", "");
  WIFI_PASS = prefs.getString("pass", "");
  API_BASE = prefs.getString("api", "");
  ESP32_TOKEN = prefs.getString("token", "");
  CONDOMINIO_ID = prefs.getString("cond", "");
  prefs.end();
  if (API_BASE.endsWith("/")) API_BASE.remove(API_BASE.length() - 1);
}

void salvarConfig(String chave, String valor) {
  prefs.begin("smartcube", false);
  prefs.putString(chave.c_str(), valor);
  prefs.end();
  Serial.println("OK salvo " + chave);
}

bool configValida() {
  // CORRIGIDO: não roda sem config, antes rodava com CONDOMINIO_ID=1 e token fake
  return WIFI_SSID.length() > 0 && WIFI_PASS.length() > 0 && API_BASE.startsWith("https://") && ESP32_TOKEN.length() >= 16 && CONDOMINIO_ID.length() > 0;
}

void conectarWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID.c_str(), WIFI_PASS.c_str());
  Serial.print("Conectando WiFi");
  // CORRIGIDO: timeout 20s + reboot, antes while(true) travava pra sempre se WiFi caísse
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) {
    delay(500);
    Serial.print(".");
    esp_task_wdt_reset();
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWiFi falhou, reiniciando em 5s");
    delay(5000);
    ESP.restart();
  }
  Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
}

bool validarBoxLado(int box, char lado) {
  // CORRIGIDO: valida antes de abrir, antes aceitava box 0, box 999, lado 'X'
  if (box < 1 || box > 64) return false;
  if (lado != 'F' && lado != 'B' && lado != 'A' && lado != 'E') return false;
  return true;
}

void abrirTrava(int box, char lado) {
  if (!validarBoxLado(box, lado)) { Serial.println("Box/lado inválido, ignorado"); return; }
  if (travaAberta) { Serial.println("Já tem trava aberta, ignorando"); return; }
  Serial.println("ABERTO:" + String(box) + ":" + String(lado));
  digitalWrite(PINO_TRAVA, HIGH);
  travaAberta = true;
  boxAberto = box;
  ladoAberto = lado;
  abertoAte = millis() + 15000;
}

void fecharTrava(int box, char lado) {
  Serial.println("FECHADO:" + String(box) + ":" + String(lado));
  digitalWrite(PINO_TRAVA, LOW);
  travaAberta = false;
  // CORRIGIDO: avisa backend que fechou de verdade, antes só fechava local e backend achava aberto
  HTTPClient http;
  http.begin(API_BASE + "/esp32/porta-evento");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", ESP32_TOKEN);
  JsonDocument doc;
  doc["evento"] = "fechada";
  doc["box"] = box;
  doc["lado"] = String(lado);
  doc["condominio_id"] = CONDOMINIO_ID;
  String body; serializeJson(doc, body);
  int code = http.POST(body);
  Serial.println("Confirmar fechamento: " + String(code));
  http.end();
}

void confirmarAbertura(String nonce, String comando_id, int box, char lado) {
  HTTPClient http;
  http.begin(API_BASE + "/esp32/porta-evento");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", ESP32_TOKEN);
  JsonDocument doc;
  doc["evento"] = "aberta";
  doc["nonce"] = nonce;
  doc["comando_id"] = comando_id;
  doc["box"] = box;
  doc["lado"] = String(lado);
  doc["condominio_id"] = CONDOMINIO_ID;
  String body; serializeJson(doc, body);
  int code = http.POST(body);
  Serial.println("Confirmar: " + String(code));
  http.end();
}

void pollPorta() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  // CORRIGIDO: HTTPS obrigatório, HTTPClient com https valida cert por padrão no ESP32
  http.begin(API_BASE + "/esp32/poll?condominio_id=" + CONDOMINIO_ID);
  http.addHeader("X-Device-Token", ESP32_TOKEN);
  http.setTimeout(5000);
  int code = http.GET();
  if (code != 200) {
    Serial.println("Poll falhou: " + String(code));
    http.end();
    return;
  }
  String payload = http.getString();
  http.end();
  if (payload.length() == 0 || payload == "null" || payload == "{}") return;

  JsonDocument doc;
  if (deserializeJson(doc, payload)) { Serial.println("JSON inválido no poll"); return; }
  if (doc["abrir"] != true) return;

  String nonce = doc["nonce"] | "";
  // CORRIGIDO: anti-replay - mesmo nonce 2x não abre 2x
  if (nonce.length() == 0 || nonce == ultimoNonce) { Serial.println("Nonce vazio ou repetido, ignorado"); return; }
  ultimoNonce = nonce;

  int box = doc["box"] | 0;
  String ladoStr = doc["lado"] | "F";
  char lado = ladoStr.length() > 0 ? ladoStr.charAt(0) : 'F';
  String comando_id = doc["comando_id"] | doc["id"] | "";
  if (!validarBoxLado(box, lado)) { Serial.println("Poll com box/lado inválido"); return; }

  abrirTrava(box, lado);
  confirmarAbertura(nonce, comando_id, box, lado);
}

void handleSerial() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  // CORRIGIDO: removido OPEN: livre via Serial - antes qualquer um com cabo USB abria qualquer box digitando OPEN:07:F
  // Serial agora só serve pra configurar e status, nunca pra abrir trava
  if (cmd.startsWith("SET ")) {
    int eq = cmd.indexOf('=');
    if (eq > 0) {
      String k = cmd.substring(4, eq); k.trim();
      String v = cmd.substring(eq + 1); v.trim();
      if (k == "WIFI_SSID") salvarConfig("ssid", v);
      else if (k == "WIFI_PASS") salvarConfig("pass", v);
      else if (k == "API_BASE") salvarConfig("api", v);
      else if (k == "TOKEN") salvarConfig("token", v);
      else if (k == "CONDOMINIO_ID") salvarConfig("cond", v);
      else Serial.println("Chave desconhecida");
    }
  } else if (cmd == "STATUS") {
    Serial.println("WiFi:" + String(WiFi.status() == WL_CONNECTED ? "OK" : "OFF") + " Trava:" + String(travaAberta ? "ABERTA" : "FECHADA") + " Box:" + String(boxAberto));
  } else if (cmd == "REBOOT") {
    ESP.restart();
  } else if (cmd == "CLEAR") {
    prefs.begin("smartcube", false); prefs.clear(); prefs.end();
    Serial.println("Config apagada");
  } else if (cmd.startsWith("OPEN")) {
    Serial.println("BLOQUEADO: OPEN via Serial desabilitado por segurança. Use o tablet/backend.");
  }
}

void setup() {
  Serial.begin(115200);
  esp_task_wdt_init(WDT_TIMEOUT, true);
  esp_task_wdt_add(NULL);
  pinMode(PINO_TRAVA, OUTPUT);
  digitalWrite(PINO_TRAVA, LOW);
  carregarConfig();
  if (!configValida()) {
    Serial.println("SEM CONFIG! Use SET ... via Serial. Ex: SET WIFI_SSID=Nome");
    Serial.println("Depois REBOOT. Trava NÃO vai abrir sem config.");
    // Fica em loop só esperando config, não conecta com dado fake
    while (!configValida()) { handleSerial(); delay(200); esp_task_wdt_reset(); carregarConfig(); }
  }
  conectarWiFi();
}

void loop() {
  esp_task_wdt_reset();
  handleSerial();
  // CORRIGIDO: millis() com overflow-safe, antes millis() > abertoAte falhava depois de 49 dias ligado
  if (travaAberta && (long)(millis() - abertoAte) >= 0) {
    fecharTrava(boxAberto, ladoAberto);
  }
  if (WiFi.status() != WL_CONNECTED) conectarWiFi();

  static unsigned long ultimoPoll = 0;
  if (millis() - ultimoPoll > 2000) {
    ultimoPoll = millis();
    pollPorta();
  }
  delay(100);
}
