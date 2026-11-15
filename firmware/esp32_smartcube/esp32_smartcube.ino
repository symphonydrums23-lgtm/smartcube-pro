#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- CONFIGURA AQUI ---
const char* WIFI_SSID = "NOME_DO_WIFI_DO_CONDOMINIO";
const char* WIFI_PASS = "SENHA_DO_WIFI";
const char* API_URL = "https://SEU-BACKEND.onrender.com/api/tablet/abrir-porta";
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
  abertoAte = millis() + 15000;
}

void fecharTrava(int box, char lado) {
  Serial.println("FECHADO:" + String(box) + ":" + String(lado));
  digitalWrite(PINO_TRAVA, LOW);
  travaAberta = false;
}

void loop() {
  if (travaAberta && millis() > abertoAte) {
    fecharTrava(boxAberto, ladoAberto);
  }
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("OPEN:")) {
      int box = cmd.substring(5, 7).toInt();
      char lado = cmd.charAt(8);
      abrirTrava(box, lado);
    }
  }
  delay(100);
}
