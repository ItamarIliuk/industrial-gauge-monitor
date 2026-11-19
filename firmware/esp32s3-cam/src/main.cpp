// Gauge Cam — dispositivo IoT de captura para o Industrial Gauge Monitor.
// Freenove ESP32-S3-WROOM CAM + OV2640: captura JPEG e envia ao Gateway por HTTP.
// Toda a análise (Cosmos3 local ou Gemini) acontece no servidor; o device só "enxerga".
//
// Configuração (Wi-Fi, URL do gateway, device_id, token, intervalo) via portal WiFiManager:
//   - abre automaticamente se não houver configuração salva;
//   - ou segure o botão BOOT (GPIO0) durante o reset.
// Rede do portal: "GaugeCam-XXXX" -> http://192.168.4.1

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiManager.h>

#include "esp_camera.h"

// ---------------- pinos da câmera (Freenove ESP32-S3-WROOM = mapeamento ESP32-S3-EYE)
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM  4
#define SIOC_GPIO_NUM  5
#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y2_GPIO_NUM    11
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7
#define PCLK_GPIO_NUM  13

#define BOOT_BUTTON 0
#ifndef RGB_LED_PIN
#define RGB_LED_PIN 48   // WS2812 da placa Freenove
#endif

static const char *FW_VERSION = "gauge-cam/1.0";

struct Config {
  String server;     // ex.: http://192.168.0.10:8090
  String deviceId;   // ex.: manometro-caldeira-01
  String token;      // token do dispositivo (o gateway guarda só o SHA-256)
  uint32_t intervalS = 10;
  uint8_t frameSize = FRAMESIZE_SVGA;  // 800x600
  bool deepSleep = false;              // true = economia de energia (bateria)
} cfg;

Preferences prefs;

// ---------------- LED de status
static void led(uint8_t r, uint8_t g, uint8_t b) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  rgbLedWrite(RGB_LED_PIN, r, g, b);
#else
  neopixelWrite(RGB_LED_PIN, r, g, b);
#endif
}

// ---------------- configuração persistente (NVS)
static void loadConfig() {
  prefs.begin("gaugecam", false);  // RW: cria o namespace na primeira execução
  cfg.server = prefs.getString("server", "");
  cfg.deviceId = prefs.getString("device", "");
  cfg.token = prefs.getString("token", "");
  cfg.intervalS = prefs.getUInt("interval", 10);
  cfg.frameSize = prefs.getUChar("fsize", FRAMESIZE_SVGA);
  cfg.deepSleep = prefs.getBool("sleep", false);
  prefs.end();
}

static void saveConfig() {
  prefs.begin("gaugecam", false);
  prefs.putString("server", cfg.server);
  prefs.putString("device", cfg.deviceId);
  prefs.putString("token", cfg.token);
  prefs.putUInt("interval", cfg.intervalS);
  prefs.putUChar("fsize", cfg.frameSize);
  prefs.putBool("sleep", cfg.deepSleep);
  prefs.end();
}

static bool configComplete() {
  return cfg.server.length() && cfg.deviceId.length() && cfg.token.length();
}

// ---------------- Wi-Fi + portal de configuração
static void connectWiFi(bool forcePortal) {
  WiFiManager wm;
  wm.setConfigPortalTimeout(300);
  char interval[8], fsize[4];
  snprintf(interval, sizeof(interval), "%u", (unsigned)cfg.intervalS);
  snprintf(fsize, sizeof(fsize), "%u", (unsigned)cfg.frameSize);

  WiFiManagerParameter pServer("server", "URL do gateway (http://IP:8090)", cfg.server.c_str(), 96);
  WiFiManagerParameter pDevice("device", "ID do dispositivo", cfg.deviceId.c_str(), 48);
  WiFiManagerParameter pToken("token", "Token do dispositivo", cfg.token.c_str(), 64, "type='password'");
  WiFiManagerParameter pInterval("interval", "Intervalo entre leituras (s)", interval, 7);
  WiFiManagerParameter pFsize("fsize", "Resolucao (8=VGA 9=SVGA 10=XGA 11=HD)", fsize, 3);
  wm.addParameter(&pServer);
  wm.addParameter(&pDevice);
  wm.addParameter(&pToken);
  wm.addParameter(&pInterval);
  wm.addParameter(&pFsize);

  bool saved = false;
  wm.setSaveParamsCallback([&]() { saved = true; });
  wm.setSaveConfigCallback([&]() { saved = true; });

  String ap = "GaugeCam-" + String((uint32_t)ESP.getEfuseMac(), HEX).substring(0, 4);
  led(0, 0, 40);  // azul = configurando / conectando
  bool ok = forcePortal ? wm.startConfigPortal(ap.c_str()) : wm.autoConnect(ap.c_str());

  if (saved) {
    cfg.server = pServer.getValue();
    cfg.deviceId = pDevice.getValue();
    if (strlen(pToken.getValue())) cfg.token = pToken.getValue();
    cfg.intervalS = max(1, atoi(pInterval.getValue()));
    cfg.frameSize = constrain(atoi(pFsize.getValue()), (int)FRAMESIZE_VGA, (int)FRAMESIZE_HD);
    while (cfg.server.endsWith("/")) cfg.server.remove(cfg.server.length() - 1);
    saveConfig();
    Serial.println("[cfg] configuração salva");
  }
  if (!ok) {
    Serial.println("[wifi] falhou; reiniciando");
    led(40, 0, 0);
    delay(2000);
    ESP.restart();
  }
  Serial.printf("[wifi] conectado: %s  RSSI %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

// ---------------- câmera
static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = (framesize_t)cfg.frameSize;
  c.jpeg_quality = 10;                 // 0-63 (menor = melhor)
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;    // sempre o frame mais novo

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("[cam] erro 0x%x ao iniciar a câmera\n", err);
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_whitebal(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  Serial.printf("[cam] OV2640 ok, frame_size=%u, PSRAM livre=%u KB\n", cfg.frameSize, ESP.getFreePsram() / 1024);
  return true;
}

static camera_fb_t *capture() {
  // descarta alguns frames para a auto-exposição estabilizar
  for (int i = 0; i < 3; i++) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
    delay(60);
  }
  return esp_camera_fb_get();
}

// ---------------- envio ao gateway
static bool sendFrame(camera_fb_t *fb) {
  HTTPClient http;
  String url = cfg.server + "/v1/ingest/" + cfg.deviceId;
  http.begin(url);
  http.setTimeout(30000);
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-Token", cfg.token);
  http.addHeader("User-Agent", FW_VERSION);

  uint32_t t0 = millis();
  int code = http.POST(fb->buf, fb->len);
  uint32_t dt = millis() - t0;
  String body = http.getString();
  http.end();

  if (code != 200) {
    Serial.printf("[http] %d em %u ms: %s\n", code, dt, body.c_str());
    led(40, 0, 0);  // vermelho = erro
    return false;
  }
  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    Serial.printf("[http] resposta inválida: %s\n", body.c_str());
    return false;
  }
  float bar = doc["bar_mediana"] | doc["bar"] | -1.0f;
  float psi = doc["psi_mediana"] | doc["psi"] | -1.0f;
  float conf = doc["confianca"] | 0.0f;
  bool alerta = doc["alerta_visibilidade"] | false;
  Serial.printf("[leitura] %.2f bar | %.1f psi | conf %.2f%s | %u KB em %u ms\n",
                bar, psi, conf, alerta ? " | ALERTA VISIBILIDADE" : "", fb->len / 1024, dt);
  if (alerta) led(40, 20, 0);     // laranja = visibilidade ruim
  else led(0, 30, 0);             // verde = ok
  return true;
}

// ---------------- ciclo
static void cycle() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] reconectando...");
    WiFi.reconnect();
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
    if (WiFi.status() != WL_CONNECTED) return;
  }
  camera_fb_t *fb = capture();
  if (!fb) {
    Serial.println("[cam] falha na captura");
    led(40, 0, 0);
    return;
  }
  sendFrame(fb);
  esp_camera_fb_return(fb);
}

// ---------------- pedido de portal (BOOT por 3 s ou comando serial) sobrevive ao reboot via NVS
static void requestPortalAndReboot() {
  prefs.begin("gaugecam", false);
  prefs.putBool("portal", true);
  prefs.end();
  Serial.println("[cfg] portal solicitado; reiniciando...");
  led(0, 0, 40);
  delay(300);
  ESP.restart();
}

static bool takePortalRequest() {
  prefs.begin("gaugecam", false);
  bool p = prefs.getBool("portal", false);
  if (p) prefs.putBool("portal", false);
  prefs.end();
  return p;
}

// ---------------- comandos pela serial (USB/UART), úteis em bancada:
//   show | token <valor> | server <url> | device <id> | interval <s> | fsize <8..11> | sleep <0|1> | portal | reboot
static void handleSerial() {
  static String line;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch != '\n' && ch != '\r') { if (line.length() < 200) line += ch; continue; }
    line.trim();
    if (!line.length()) continue;
    int sp = line.indexOf(' ');
    String cmd = sp < 0 ? line : line.substring(0, sp);
    String arg = sp < 0 ? "" : line.substring(sp + 1);
    arg.trim();
    line = "";
    bool changed = true;
    if (cmd == "token" && arg.length()) cfg.token = arg;
    else if (cmd == "server" && arg.length()) { cfg.server = arg; while (cfg.server.endsWith("/")) cfg.server.remove(cfg.server.length() - 1); }
    else if (cmd == "device" && arg.length()) cfg.deviceId = arg;
    else if (cmd == "interval" && arg.toInt() > 0) cfg.intervalS = arg.toInt();
    else if (cmd == "fsize" && arg.toInt() >= FRAMESIZE_VGA && arg.toInt() <= FRAMESIZE_HD) cfg.frameSize = arg.toInt();
    else if (cmd == "sleep") cfg.deepSleep = arg.toInt() != 0;
    else {
      changed = false;
      if (cmd == "portal") requestPortalAndReboot();
      else if (cmd == "reboot") ESP.restart();
      else if (cmd != "show") Serial.println("[cmd] comandos: show | token | server | device | interval | fsize | sleep | portal | reboot");
    }
    if (changed) { saveConfig(); Serial.printf("[cmd] %s salvo%s\n", cmd.c_str(), cmd == "fsize" ? " (vale após reboot)" : ""); }
    // o token nunca é impresso: só o tamanho
    Serial.printf("[cfg] server=%s device=%s token=<%u caracteres> interval=%us fsize=%u sleep=%d\n",
                  cfg.server.c_str(), cfg.deviceId.c_str(), cfg.token.length(), (unsigned)cfg.intervalS,
                  cfg.frameSize, cfg.deepSleep);
  }
}

// espera o intervalo atendendo a serial e o botão BOOT (segurar 3 s = portal)
static void waitInterval(uint32_t ms) {
  uint32_t start = millis(), pressedAt = 0;
  while (millis() - start < ms) {
    handleSerial();
    if (digitalRead(BOOT_BUTTON) == LOW) {
      if (!pressedAt) pressedAt = millis();
      else if (millis() - pressedAt > 3000) requestPortalAndReboot();
    } else {
      pressedAt = 0;
    }
    delay(20);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BOOT_BUTTON, INPUT_PULLUP);
  Serial.printf("\n=== %s ===\n", FW_VERSION);
  Serial.println("[dica] segure BOOT por 3 s (com a placa rodando) para abrir o portal; ou digite 'show' na serial");

  loadConfig();
  bool forcePortal = takePortalRequest() || !configComplete();
  if (forcePortal) Serial.println("[cfg] abrindo portal de configuração (GaugeCam-XXXX)");
  connectWiFi(forcePortal);

  if (!configComplete()) {
    Serial.println("[cfg] configuração incompleta; reiniciando no portal");
    delay(1000);
    ESP.restart();
  }
  if (!initCamera()) {
    led(40, 0, 0);
    delay(5000);
    ESP.restart();
  }
  Serial.printf("[cfg] gateway=%s device=%s intervalo=%us\n", cfg.server.c_str(), cfg.deviceId.c_str(), (unsigned)cfg.intervalS);
}

void loop() {
  cycle();
  if (cfg.deepSleep) {
    esp_camera_deinit();
    esp_sleep_enable_timer_wakeup((uint64_t)cfg.intervalS * 1000000ULL);
    Serial.flush();
    esp_deep_sleep_start();
  }
  waitInterval(cfg.intervalS * 1000UL);
}
