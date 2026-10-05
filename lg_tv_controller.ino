#include <WiFi.h>
#include <WebServer.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>

// Set these for the controller's local network.
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// This stable name is what Wazen stores and uses to rediscover a changed IP.
const char* DEVICE_NAME = "LG TV IR Controller";
const char* DEVICE_TYPE = "lg_tv_ir";
const char* DEVICE_HOSTNAME = "lg-tv-ir-controller";
const char* FIRMWARE_VERSION = "1.1.0";
const char* IDENTITY_PROTOCOL = "wazen-device-identity/1";

const uint8_t IR_SEND_PINS[] = {18, 23, 15};
const size_t IR_COUNT = sizeof(IR_SEND_PINS) / sizeof(IR_SEND_PINS[0]);

IRsend ir1(IR_SEND_PINS[0]);
IRsend ir2(IR_SEND_PINS[1]);
IRsend ir3(IR_SEND_PINS[2]);
WebServer server(80);

struct LGCommand {
  const char* name;
  uint32_t code;
};

const LGCommand COMMANDS[] = {
  {"POWER", 0x20DF10EF}, {"VOL_UP", 0x20DF40BF},
  {"VOL_DOWN", 0x20DFC03F}, {"MUTE", 0x20DF906F},
  {"CH_UP", 0x20DF00FF}, {"CH_DOWN", 0x20DF807F},
  {"INPUT", 0x20DFD02F}, {"HOME", 0x20DF3EC1},
  {"SETTINGS", 0x20DFC23D}, {"UP", 0x20DF02FD},
  {"DOWN", 0x20DF827D}, {"LEFT", 0x20DFE01F},
  {"RIGHT", 0x20DF609F}, {"OK", 0x20DF22DD},
  {"BACK", 0x20DF14EB}, {"EXIT", 0x20DFDA25},
  {"0", 0x20DF08F7}, {"1", 0x20DF8877},
  {"2", 0x20DF48B7}, {"3", 0x20DFC837},
  {"4", 0x20DF28D7}, {"5", 0x20DFA857},
  {"6", 0x20DF6897}, {"7", 0x20DFE817},
  {"8", 0x20DF18E7}, {"9", 0x20DF9867},
};
const size_t COMMAND_COUNT = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

void sendJSON(int status, const String& body) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(status, "application/json", body);
}

bool executeCommand(const String& name) {
  for (size_t index = 0; index < COMMAND_COUNT; index++) {
    if (name == COMMANDS[index].name) {
      const uint32_t code = COMMANDS[index].code;
      ir1.sendNEC(code, 32);
      ir2.sendNEC(code, 32);
      ir3.sendNEC(code, 32);
      Serial.printf("Command %s sent as 0x%08lX\n", name.c_str(), code);
      return true;
    }
  }
  return false;
}

void handleCommand(const char* command) {
  if (!executeCommand(String(command))) {
    sendJSON(404, "{\"success\":false,\"error\":\"unknown_command\"}");
    return;
  }
  String response = "{\"success\":true,\"command\":\"";
  response += command;
  response += "\"}";
  sendJSON(200, response);
}

void handleIdentity() {
  char deviceId[24];
  snprintf(deviceId, sizeof(deviceId), "esp32-%012llx", ESP.getEfuseMac());
  String response = "{\"protocol\":\"";
  response += IDENTITY_PROTOCOL;
  response += "\",\"device_name\":\"";
  response += DEVICE_NAME;
  response += "\",\"device_type\":\"";
  response += DEVICE_TYPE;
  response += "\",\"device_id\":\"";
  response += deviceId;
  response += "\",\"hostname\":\"";
  response += DEVICE_HOSTNAME;
  response += "\",\"firmware_version\":\"";
  response += FIRMWARE_VERSION;
  response += "\",\"capabilities\":[\"lg_tv_remote\",\"ir_send\"]}";
  sendJSON(200, response);
}

void handleStatus() {
  String response = "{\"success\":true,\"status\":\"online\",\"device_name\":\"";
  response += DEVICE_NAME;
  response += "\",\"ip\":\"";
  response += WiFi.localIP().toString();
  response += "\",\"rssi\":";
  response += String(WiFi.RSSI());
  response += "}";
  sendJSON(200, response);
}

// Keep the original endpoint available for direct diagnostics.
void handleLegacyIR() {
  if (!server.hasArg("cmd")) {
    sendJSON(400, "{\"success\":false,\"error\":\"missing_command\"}");
    return;
  }
  const String command = server.arg("cmd");
  if (!executeCommand(command)) {
    sendJSON(404, "{\"success\":false,\"error\":\"unknown_command\"}");
    return;
  }
  String response = "{\"success\":true,\"command\":\"" + command + "\"}";
  sendJSON(200, response);
}

void registerRoutes() {
  server.on("/", HTTP_GET, []() {
    server.send(200, "text/plain", "LG TV IR Controller");
  });
  server.on("/identity", HTTP_GET, handleIdentity);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/ir", HTTP_GET, handleLegacyIR);

  server.on("/api/ir/power", HTTP_POST, []() { handleCommand("POWER"); });
  server.on("/api/ir/volume/up", HTTP_POST, []() { handleCommand("VOL_UP"); });
  server.on("/api/ir/volume/down", HTTP_POST, []() { handleCommand("VOL_DOWN"); });
  server.on("/api/ir/mute", HTTP_POST, []() { handleCommand("MUTE"); });
  server.on("/api/ir/channel/up", HTTP_POST, []() { handleCommand("CH_UP"); });
  server.on("/api/ir/channel/down", HTTP_POST, []() { handleCommand("CH_DOWN"); });
  server.on("/api/ir/input", HTTP_POST, []() { handleCommand("INPUT"); });
  server.on("/api/ir/home", HTTP_POST, []() { handleCommand("HOME"); });
  server.on("/api/ir/settings", HTTP_POST, []() { handleCommand("SETTINGS"); });
  server.on("/api/ir/navigation/up", HTTP_POST, []() { handleCommand("UP"); });
  server.on("/api/ir/navigation/down", HTTP_POST, []() { handleCommand("DOWN"); });
  server.on("/api/ir/navigation/left", HTTP_POST, []() { handleCommand("LEFT"); });
  server.on("/api/ir/navigation/right", HTTP_POST, []() { handleCommand("RIGHT"); });
  server.on("/api/ir/navigation/ok", HTTP_POST, []() { handleCommand("OK"); });
  server.on("/api/ir/back", HTTP_POST, []() { handleCommand("BACK"); });
  server.on("/api/ir/exit", HTTP_POST, []() { handleCommand("EXIT"); });
  server.on("/api/ir/number/0", HTTP_POST, []() { handleCommand("0"); });
  server.on("/api/ir/number/1", HTTP_POST, []() { handleCommand("1"); });
  server.on("/api/ir/number/2", HTTP_POST, []() { handleCommand("2"); });
  server.on("/api/ir/number/3", HTTP_POST, []() { handleCommand("3"); });
  server.on("/api/ir/number/4", HTTP_POST, []() { handleCommand("4"); });
  server.on("/api/ir/number/5", HTTP_POST, []() { handleCommand("5"); });
  server.on("/api/ir/number/6", HTTP_POST, []() { handleCommand("6"); });
  server.on("/api/ir/number/7", HTTP_POST, []() { handleCommand("7"); });
  server.on("/api/ir/number/8", HTTP_POST, []() { handleCommand("8"); });
  server.on("/api/ir/number/9", HTTP_POST, []() { handleCommand("9"); });
  server.onNotFound([]() {
    sendJSON(404, "{\"success\":false,\"error\":\"not_found\"}");
  });
}

void setup() {
  Serial.begin(115200);
  ir1.begin();
  ir2.begin();
  ir3.begin();

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
  }
  Serial.printf("\nLG TV controller online at http://%s\n", WiFi.localIP().toString().c_str());

  registerRoutes();
  server.begin();
}

void loop() {
  server.handleClient();
  delay(2);
}
