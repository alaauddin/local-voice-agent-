#include <Arduino.h>

#include <WiFi.h>

#include <WebServer.h>

#include <Preferences.h>

#include <ArduinoJson.h>



#define RAW_BUFFER_LENGTH 1500

#define RECORD_GAP_MICROS 50000

#define USE_16_BIT_TIMING_BUFFER



#include <IRremote.hpp>



const char* WIFI_SSID = "ala";
const char* WIFI_PASSWORD = "alauddin";

const char* DEVICE_NAME = "ESP32 IR Controller";
const char* DEVICE_TYPE = "esp32";
const char* DEVICE_HOSTNAME = "esp32-ir-controller";
const char* DEVICE_MANUFACTURER = "Espressif";
const char* FIRMWARE_VERSION = "1.0.0";
const char* IDENTITY_PROTOCOL = "wazen-device-identity/1";




// Receiver input and three independent transmitter outputs.

const uint8_t IR_RECEIVE_PIN = 25;

const uint8_t IR_SEND_PINS[] = {18, 32, 27};

const size_t IR_SEND_PIN_COUNT =

  sizeof(IR_SEND_PINS) / sizeof(IR_SEND_PINS[0]);

const uint8_t IR_ID = 1;



const uint32_t CAPTURE_TIMEOUT_MS = 15000;

const uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;

const uint32_t WIFI_RETRY_INTERVAL_MS = 10000;



WebServer server(80);

Preferences preferences;



uint16_t savedRaw[RAW_BUFFER_LENGTH];



uint16_t savedRawLength = 0;

uint8_t savedFrequency = 38;

uint8_t captureFrequency = 38;



String savedProtocol = "UNKNOWN";



bool hasSavedSignal = false;

bool captureEnabled = false;



unsigned long captureStartedAt = 0;

unsigned long lastReconnectAttempt = 0;
uint32_t signalRevision = 0;

wl_status_t lastWiFiStatus = WL_NO_SHIELD;





String buildRawJSON() {

  String result;



  result.reserve(savedRawLength * 6);



  result += "[";



  for (uint16_t i = 0; i < savedRawLength; i++) {

    result += String(savedRaw[i]);



    if (i < savedRawLength - 1) {

      result += ",";

    }

  }



  result += "]";



  return result;

}





String buildCurlCommand() {

  String ip = WiFi.localIP().toString();



  String command;



  command.reserve(savedRawLength * 7 + 300);



  command += "curl -X POST \"http://";

  command += ip;

  command += "/ir\" ";

  command += "-H \"Content-Type: application/json\" ";

  command += "-d '{";

  command += "\"id\":";

  command += String(IR_ID);

  command += ",";

  command += "\"frequency\":";

  command += String(savedFrequency);

  command += ",";

  command += "\"raw\":";

  command += buildRawJSON();

  command += "}'";



  return command;

}





void saveIRToFlash() {

  preferences.begin("ir-store", false);



  preferences.putUShort(

    "length",

    savedRawLength

  );



  preferences.putUChar(

    "frequency",

    savedFrequency

  );



  preferences.putString(

    "protocol",

    savedProtocol

  );



  preferences.putBytes(

    "raw",

    savedRaw,

    savedRawLength * sizeof(uint16_t)

  );



  preferences.end();

}





void loadIRFromFlash() {

  preferences.begin("ir-store", true);



  savedRawLength =

    preferences.getUShort("length", 0);



  if (

    savedRawLength > 0 &&

    savedRawLength <= RAW_BUFFER_LENGTH

  ) {

    size_t expectedBytes =

      savedRawLength * sizeof(uint16_t);



    size_t storedBytes =

      preferences.getBytesLength("raw");



    if (storedBytes == expectedBytes) {

      preferences.getBytes(

        "raw",

        savedRaw,

        expectedBytes

      );



      savedFrequency =

        preferences.getUChar(

          "frequency",

          38

        );



      if (

        savedFrequency < 20 ||

        savedFrequency > 100

      ) {

        savedFrequency = 38;

      }



      captureFrequency = savedFrequency;



      savedProtocol =

        preferences.getString(

          "protocol",

          "UNKNOWN"

        );



      hasSavedSignal = true;

    }

  }



  preferences.end();

}





void clearSavedSignal() {

  preferences.begin("ir-store", false);

  preferences.clear();

  preferences.end();



  savedRawLength = 0;

  savedFrequency = 38;

  captureFrequency = 38;

  savedProtocol = "UNKNOWN";



  hasSavedSignal = false;

}





bool sendRawSignal(

  uint16_t* data,

  size_t length,

  uint8_t frequency

) {

  if (

    data == nullptr ||

    length == 0 ||

    length > RAW_BUFFER_LENGTH ||

    frequency < 20 ||

    frequency > 100

  ) {

    return false;

  }



  captureEnabled = false;

  IrReceiver.stop();



  delay(2);



  for (size_t i = 0; i < IR_SEND_PIN_COUNT; i++) {

    IrSender.setSendPin(IR_SEND_PINS[i]);



    IrSender.sendRaw(

      data,

      length,

      frequency

    );



    digitalWrite(

      IR_SEND_PINS[i],

      LOW

    );



    if (i + 1 < IR_SEND_PIN_COUNT) {

      delay(5);

    }

  }



  IrSender.setSendPin(IR_SEND_PINS[0]);



  IrReceiver.start();



  return true;

}





bool copyReceivedRaw() {

  if (IrReceiver.irparams.rawlen <= 1) {

    return false;

  }



  uint16_t length =

    IrReceiver.irparams.rawlen - 1;



  if (length > RAW_BUFFER_LENGTH) {

    return false;

  }



  for (

    IRRawlenType i = 1;

    i < IrReceiver.irparams.rawlen;

    i++

  ) {

    uint32_t value =

      (uint32_t)

      IrReceiver.irparams.rawbuf[i] *

      MICROS_PER_TICK;



    if (i & 1) {

      if (value > MARK_EXCESS_MICROS) {

        value -= MARK_EXCESS_MICROS;

      }

    } else {

      value += MARK_EXCESS_MICROS;

    }



    if (

      value == 0 ||

      value > 65535

    ) {

      return false;

    }



    savedRaw[i - 1] =

      (uint16_t)value;

  }



  savedRawLength = length;



  return true;

}





const char PAGE[] PROGMEM = R"rawliteral(

<!DOCTYPE html>

<html>



<head>



<meta name="viewport"

content="width=device-width, initial-scale=1">



<title>ESP32 IR Discover</title>



<style>



body {

  font-family: Arial, sans-serif;

  background: #111827;

  color: white;

  margin: 0;

  padding: 25px 15px;

}



.container {

  max-width: 750px;

  margin: auto;

}



.card {

  background: #1f2937;

  padding: 25px;

  border-radius: 15px;

  margin-bottom: 20px;

}



h1, h3 {

  text-align: center;

}



button {

  width: 100%;

  padding: 15px;

  margin-top: 12px;

  border: none;

  border-radius: 9px;

  font-size: 16px;

  cursor: pointer;

}



.discover {

  background: #2563eb;

  color: white;

}



.send {

  background: #16a34a;

  color: white;

}



.delete {

  background: #dc2626;

  color: white;

}



.copy {

  background: #6b7280;

  color: white;

}



input,

select {

  width: 100%;

  box-sizing: border-box;

  padding: 12px;

  font-size: 18px;

  text-align: center;

  border-radius: 8px;

  border: none;

}



textarea {

  width: 100%;

  box-sizing: border-box;

  min-height: 180px;

  background: #0f172a;

  color: #4ade80;

  border: 1px solid #374151;

  border-radius: 8px;

  padding: 12px;

  font-family: monospace;

  font-size: 13px;

  resize: vertical;

}



.info {

  text-align: center;

  line-height: 1.8;

}



.waiting {

  color: #facc15;

}



.ready {

  color: #4ade80;

}



.none {

  color: #f87171;

}



</style>



</head>



<body>



<div class="container">



<div class="card">



<h1>ESP32 IR Discover</h1>



<div id="status"
class="info">
Loading...
</div>

<div class="info">
IP:
<strong id="deviceIp">-</strong>
</div>

</div>





<div class="card">



<h3>Discover Signal</h3>



<p class="info">

Receiver GPIO25. Capture starts when you press this button.

One Send action transmits through GPIO18, GPIO32, then GPIO27.

</p>



<input

id="frequency"

type="number"

min="20"

max="100"

value="38">



<button

class="discover"

onclick="discoverIR()">

Discover IR

</button>



</div>





<div class="card">



<h3>Saved Signal</h3>



<div class="info">



Protocol:

<strong id="protocol">-</strong>



<br>



RAW timings:

<strong id="length">0</strong>



<br>



Frequency:

<strong id="savedFrequency">-</strong>



</div>



<button

class="send"

onclick="sendSaved()">

Send Saved IR

</button>



<button
class="delete"
onclick="deleteSaved()">
Delete Saved IR
</button>

<h3>Captured RAW Signal</h3>
<textarea id="rawSignal" readonly>No signal captured yet.</textarea>
<button class="copy" onclick="copyField('rawSignal')">
Copy RAW
</button>

<h3>cURL Command</h3>
<textarea id="curlCommand" readonly>No signal captured yet.</textarea>
<button class="copy" onclick="copyField('curlCommand')">
Copy cURL
</button>

</div>





</div>





<script>

let lastSignalKey = "";

async function request(path, options = {}) {

  const response =

    await fetch(

      path,

      Object.assign(

        { cache: "no-store" },

        options

      )

    );



  const text =

    await response.text();



  if (!response.ok) {

    try {

      const data = JSON.parse(text);

      throw new Error(data.message || text);

    } catch (error) {

      if (error instanceof SyntaxError) {

        throw new Error(

          text || "HTTP " + response.status

        );

      }



      throw error;

    }

  }



  return text;

}





async function discoverIR() {

  const frequency =

    document.getElementById(

      "frequency"

    ).value;



  try {

    await request(

      "/capture?frequency=" +

      encodeURIComponent(frequency),

      { method: "POST" }

    );



    
    lastSignalKey = "";

    updateStatus();

  } catch (error) {

    alert(error.message);

  }

}





async function sendSaved() {

  try {

    const result =

      await request(

        "/send",

        { method: "POST" }

      );



    alert(result);

  } catch (error) {

    alert(error.message);

  }

}





async function loadSignalDetails() {
  const rawBox = document.getElementById("rawSignal");
  const curlBox = document.getElementById("curlCommand");

  try {
    rawBox.value = await request("/raw");
    curlBox.value = await request("/curl");
  } catch (error) {
    rawBox.value = "No signal captured yet.";
    curlBox.value = "No signal captured yet.";
  }
}


async function copyField(id) {
  const el = document.getElementById(id);

  try {
    await navigator.clipboard.writeText(el.value);
  } catch (error) {
    el.select();
    document.execCommand("copy");
  }
}


async function deleteSaved() {

  try {

    await request(

      "/delete",

      { method: "POST" }

    );



    updateStatus();

  } catch (error) {

    alert(error.message);

  }

}





async function updateStatus() {

  try {

    const d =

      JSON.parse(

        await request("/status")

      );



    const status =

      document.getElementById(

        "status"

      );



    if (d.capturing) {

      status.innerHTML =

        "Waiting for IR signal...";



      status.className =

        "info waiting";

    }



    else if (d.hasSignal) {

      status.innerHTML =

        "IR signal saved";



      status.className =

        "info ready";

    }



    else {

      status.innerHTML =

        "No saved signal";



      status.className =

        "info none";

    }





    document.getElementById(

      "protocol"

    ).innerText =

      d.protocol;





    document.getElementById(

      "length"

    ).innerText =

      d.length;





    document.getElementById(

      "savedFrequency"

    ).innerText =

      d.hasSignal ?

      d.frequency + " kHz" :

      "-";

    document.getElementById("deviceIp").innerText =
      d.ip || "-";

    if (d.hasSignal) {
      const signalKey = String(d.revision);

      if (signalKey !== lastSignalKey) {
        lastSignalKey = signalKey;
        await loadSignalDetails();
      }
    } else {
      lastSignalKey = "";
      document.getElementById("rawSignal").value =
        "No signal captured yet.";
      document.getElementById("curlCommand").value =
        "No signal captured yet.";
    }



  } catch(e) {

  }

}





setInterval(

  updateStatus,

  1000

);



updateStatus();



</script>



</body>



</html>

)rawliteral";





void handleRoot() {

  server.send_P(

    200,

    "text/html",

    PAGE

  );

}



void handleIdentity() {

  JsonDocument doc;



  doc["protocol"] = IDENTITY_PROTOCOL;

  doc["type"] = DEVICE_TYPE;

  doc["name"] = DEVICE_NAME;

  doc["device_type"] = DEVICE_TYPE;

  doc["device_name"] = DEVICE_NAME;

  doc["device_id"] = WiFi.macAddress();

  doc["hostname"] = DEVICE_HOSTNAME;

  doc["manufacturer"] = DEVICE_MANUFACTURER;

  doc["model"] = ESP.getChipModel();

  doc["firmware_version"] = FIRMWARE_VERSION;

  doc["ip"] = WiFi.localIP().toString();

  doc["mac"] = WiFi.macAddress();

  doc["ssid"] = WiFi.SSID();

  doc["rssi"] = WiFi.RSSI();

  doc["uptime_ms"] = millis();



  JsonArray capabilities =

    doc["capabilities"].to<JsonArray>();



  capabilities.add("ir_receive");

  capabilities.add("ir_transmit");

  capabilities.add("http_api");



  String response;

  serializeJson(doc, response);



  server.sendHeader(

    "Cache-Control",

    "no-store"

  );



  server.send(

    200,

    "application/json",

    response

  );

}





void handleCapture() {

  if (server.hasArg("frequency")) {

    String value = server.arg("frequency");

    char* end = nullptr;

    long frequency = strtol(value.c_str(), &end, 10);



    if (

      value.length() > 0 &&

      *end == '\0' &&

      frequency >= 20 &&

      frequency <= 100

    ) {

      captureFrequency =

        (uint8_t)frequency;

    } else {

      server.send(

        400,

        "application/json",

        "{\"status\":\"error\",\"message\":\"frequency must be 20-100 kHz\"}"

      );



      return;

    }

  }



  captureEnabled = true;



  captureStartedAt =

    millis();



  Serial.println();

  Serial.println("DISCOVER ARMED");

  Serial.println("Press ONE remote button.");



  server.send(

    200,

    "text/plain",

    "Waiting for IR signal"

  );

}





void handleStatus() {

  String json;



  json.reserve(420);



  json += "{";



  json += "\"capturing\":";

  json +=

    captureEnabled ?

    "true" :

    "false";



  json += ",";



  json += "\"hasSignal\":";

  json +=

    hasSavedSignal ?

    "true" :

    "false";



  json += ",";



  json += "\"protocol\":\"";

  json += savedProtocol;

  json += "\",";



  json += "\"length\":";

  json += String(savedRawLength);

  json += ",";



  json += "\"frequency\":";

  json += String(savedFrequency);

  json += ",";

  json += "\"revision\":";
  json += String(signalRevision);
  json += ",";



  json += "\"ip\":\"";

  json += WiFi.localIP().toString();

  json += "\",";



  json += "\"receiverGpio\":";

  json += String(IR_RECEIVE_PIN);

  json += ",";



  json += "\"sendGpios\":[";



  for (size_t i = 0; i < IR_SEND_PIN_COUNT; i++) {

    if (i > 0) {

      json += ",";

    }



    json += String(IR_SEND_PINS[i]);

  }



  json += "]";



  json += "}";



  server.send(

    200,

    "application/json",

    json

  );

}





void handleRaw() {
  if (!hasSavedSignal) {
    server.send(
      404,
      "text/plain",
      "No signal saved"
    );
    return;
  }

  server.send(
    200,
    "application/json",
    buildRawJSON()
  );
}


void handleCurl() {

  if (!hasSavedSignal) {

    server.send(

      404,

      "text/plain",

      "No signal saved"

    );



    return;

  }



  server.send(

    200,

    "text/plain",

    buildCurlCommand()

  );

}





void handleSend() {

  if (

    !hasSavedSignal ||

    savedRawLength == 0

  ) {

    server.send(

      400,

      "text/plain",

      "No IR signal saved"

    );



    return;

  }



  if (

    sendRawSignal(

      savedRaw,

      savedRawLength,

      savedFrequency

    )

  ) {

    server.send(

      200,

      "text/plain",

      "IR sent"

    );

  } else {

    server.send(

      500,

      "text/plain",

      "Send failed"

    );

  }

}





void handleDelete() {

  clearSavedSignal();



  server.send(

    200,

    "text/plain",

    "Deleted"

  );

}





void handleApiIR() {

  if (!server.hasArg("plain")) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"body missing\"}"

    );



    return;

  }



  const String body =

    server.arg("plain");



  if (

    body.length() == 0 ||

    body.length() > 12000

  ) {

    server.send(

      413,

      "application/json",

      "{\"status\":\"error\",\"message\":\"body is empty or too large\"}"

    );



    return;

  }



  JsonDocument doc;



  DeserializationError error =

    deserializeJson(

      doc,

      body

    );



  if (error) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"invalid json\"}"

    );



    return;

  }



  if (!doc["frequency"].is<int>()) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"frequency missing\"}"

    );



    return;

  }



  if (!doc["raw"].is<JsonArray>()) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"raw missing\"}"

    );



    return;

  }



  int id =

    doc["id"] | IR_ID;



  if (id != IR_ID) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"invalid id\"}"

    );



    return;

  }



  int frequency =

    doc["frequency"].as<int>();



  if (

    frequency < 20 ||

    frequency > 100

  ) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"invalid frequency\"}"

    );



    return;

  }



  JsonArray raw =

    doc["raw"].as<JsonArray>();



  size_t length =

    raw.size();



  if (

    length == 0 ||

    length > RAW_BUFFER_LENGTH

  ) {

    server.send(

      400,

      "application/json",

      "{\"status\":\"error\",\"message\":\"invalid raw length\"}"

    );



    return;

  }



  static uint16_t apiRaw[

    RAW_BUFFER_LENGTH

  ];



  for (

    size_t i = 0;

    i < length;

    i++

  ) {

    if (!raw[i].is<unsigned long>()) {

      server.send(

        400,

        "application/json",

        "{\"status\":\"error\",\"message\":\"invalid raw value\"}"

      );



      return;

    }



    unsigned long value =

      raw[i].as<unsigned long>();



    if (

      value == 0 ||

      value > 65535

    ) {

      server.send(

        400,

        "application/json",

        "{\"status\":\"error\",\"message\":\"raw timing out of range\"}"

      );



      return;

    }



    apiRaw[i] =

      (uint16_t)value;

  }



  if (!sendRawSignal(

        apiRaw,

        length,

        (uint8_t)frequency

      )) {

    server.send(

      500,

      "application/json",

      "{\"status\":\"error\",\"message\":\"IR transmission failed\"}"

    );



    return;

  }



  String response =

    "{\"status\":\"success\",\"id\":" +

    String(id) +

    ",\"gpios\":[18,32,27]" +

    ",\"frequency\":" +

    String(frequency) +

    ",\"raw_length\":" +

    String(length) +

    "}";



  server.send(

    200,

    "application/json",

    response

  );

}





void processIR() {

  if (!captureEnabled) {

    return;

  }



  if (!IrReceiver.decode()) {

    return;

  }



  if (

    IrReceiver.decodedIRData.flags &

    IRDATA_FLAGS_WAS_OVERFLOW

  ) {

    Serial.println(

      "RAW BUFFER OVERFLOW"

    );



    captureEnabled = false;



    IrReceiver.resume();



    return;

  }



  if (IrReceiver.irparams.rawlen < 6) {

    IrReceiver.resume();

    return;

  }



  if (!copyReceivedRaw()) {

    Serial.println(

      "Could not store RAW signal"

    );



    captureEnabled = false;



    IrReceiver.resume();



    return;

  }



  savedProtocol =

    getProtocolString(

      IrReceiver.decodedIRData.protocol

    );



  savedFrequency = captureFrequency;

  hasSavedSignal = true;

  captureEnabled = false;

  signalRevision++;



  saveIRToFlash();



  Serial.println();

  Serial.println(

    "IR DISCOVERED"

  );



  Serial.print(

    "Protocol: "

  );



  Serial.println(

    savedProtocol

  );



  Serial.print(

    "Frequency: "

  );



  Serial.print(

    savedFrequency

  );



  Serial.println(

    " kHz"

  );



  Serial.print(

    "RAW Length: "

  );



  Serial.println(

    savedRawLength

  );



  Serial.println();

  Serial.println(

    "CURL:"

  );



  Serial.println(

    buildCurlCommand()

  );



  IrReceiver.resume();

}





const char* wifiStatusName(wl_status_t status) {

  switch (status) {

    case WL_IDLE_STATUS:

      return "IDLE";

    case WL_NO_SSID_AVAIL:

      return "SSID NOT FOUND";

    case WL_SCAN_COMPLETED:

      return "SCAN COMPLETED";

    case WL_CONNECTED:

      return "CONNECTED";

    case WL_CONNECT_FAILED:

      return "CONNECT FAILED";

    case WL_CONNECTION_LOST:

      return "CONNECTION LOST";

    case WL_DISCONNECTED:

      return "DISCONNECTED";

    default:

      return "UNKNOWN";

  }

}





void startWiFiAttempt() {

  // Restart the station connection completely. WiFi.reconnect() alone may not

  // recover when the first connection attempt ended as WL_DISCONNECTED.

  WiFi.disconnect(false, false);

  delay(100);



  WiFi.begin(

    WIFI_SSID,

    WIFI_PASSWORD

  );



  lastReconnectAttempt = millis();

}





void connectWiFi() {

  WiFi.persistent(false);

  WiFi.mode(WIFI_STA);



  WiFi.setHostname(DEVICE_HOSTNAME);

  WiFi.setSleep(false);

  WiFi.setAutoReconnect(true);



  Serial.print("Connecting to WiFi SSID: ");

  Serial.println(WIFI_SSID);


  startWiFiAttempt();



  unsigned long startedAt =

    millis();



  while (

    WiFi.status() != WL_CONNECTED &&

    millis() - startedAt < WIFI_CONNECT_TIMEOUT_MS

  ) {

    delay(500);

    Serial.print(".");

  }



  Serial.println();



  wl_status_t status =

    WiFi.status();



  lastWiFiStatus = status;



  if (status == WL_CONNECTED) {

    Serial.print("WiFi connected. Open: http://");

    Serial.println(WiFi.localIP());

  } else {

    Serial.print("Initial WiFi connection timed out: ");

    Serial.println(wifiStatusName(status));

    Serial.println("Web server will start and WiFi will retry every 10 seconds.");

  }

}





void serviceWiFi() {

  wl_status_t currentStatus =

    WiFi.status();



  if (currentStatus != lastWiFiStatus) {

    lastWiFiStatus = currentStatus;



    if (currentStatus == WL_CONNECTED) {

      Serial.print("WiFi connected. Open: http://");

      Serial.println(WiFi.localIP());

    } else {

      Serial.print("WiFi status: ");

      Serial.print(wifiStatusName(currentStatus));

      Serial.print(" (");

      Serial.print((int)currentStatus);

      Serial.println(")");

    }

  }



  if (

    currentStatus != WL_CONNECTED &&

    millis() - lastReconnectAttempt >= WIFI_RETRY_INTERVAL_MS

  ) {

    Serial.println("Restarting WiFi connection...");

    startWiFiAttempt();

  }

}





void setup() {

  Serial.begin(115200);



  delay(1000);



  loadIRFromFlash();



  for (size_t i = 0; i < IR_SEND_PIN_COUNT; i++) {

    pinMode(IR_SEND_PINS[i], OUTPUT);

    digitalWrite(IR_SEND_PINS[i], LOW);

  }



  IrSender.begin(IR_SEND_PINS[0]);



  IrReceiver.begin(

    IR_RECEIVE_PIN,

    DISABLE_LED_FEEDBACK

  );



  connectWiFi();



  server.on(

    "/identity",

    HTTP_GET,

    handleIdentity

  );



  server.on(

    "/whoami",

    HTTP_GET,

    handleIdentity

  );



  server.on(

    "/",

    HTTP_GET,

    handleRoot

  );



  server.on(

    "/capture",

    HTTP_GET,

    handleCapture

  );



  server.on(

    "/capture",

    HTTP_POST,

    handleCapture

  );



  server.on(

    "/status",

    HTTP_GET,

    handleStatus

  );



  server.on(
    "/raw",
    HTTP_GET,
    handleRaw
  );

  server.on(

    "/curl",

    HTTP_GET,

    handleCurl

  );



  server.on(

    "/send",

    HTTP_GET,

    handleSend

  );



  server.on(

    "/send",

    HTTP_POST,

    handleSend

  );



  server.on(

    "/delete",

    HTTP_GET,

    handleDelete

  );



  server.on(

    "/delete",

    HTTP_POST,

    handleDelete

  );



  server.on(

    "/ir",

    HTTP_POST,

    handleApiIR

  );



  server.onNotFound(

    []() {

      server.send(

        404,

        "application/json",

        "{\"status\":\"error\",\"message\":\"endpoint not found\"}"

      );

    }

  );



  server.begin();



  Serial.println(

    "Web server ready"

  );



  Serial.print("IR receiver: GPIO");

  Serial.println(IR_RECEIVE_PIN);



  Serial.println("IR send sequence:");



  for (size_t i = 0; i < IR_SEND_PIN_COUNT; i++) {

    Serial.print("  Sender ");

    Serial.print(i + 1);

    Serial.print(": GPIO");

    Serial.println(IR_SEND_PINS[i]);

  }

}





void loop() {

  server.handleClient();



  processIR();



  serviceWiFi();



  if (

    captureEnabled &&

    millis() - captureStartedAt >

    CAPTURE_TIMEOUT_MS

  ) {

    captureEnabled = false;



    Serial.println(

      "Discover timeout"

    );

  }



  delay(1);

}
