#include "ac_controller.h"

#include <strings.h>

// IRremoteESP8266 stays in this translation unit. The sketch renames the
// header-only Arduino-IRremote symbols, allowing both libraries to coexist.
#include <IRac.h>
#include <ir_Kelon.h>

namespace {

const uint8_t AC_PERSISTENCE_SCHEMA = 2;

struct PersistedACState {
  uint8_t schema;
  uint8_t power;
  uint8_t mode;
  uint8_t temperature;
  uint8_t fan;
  uint8_t flags;
  uint32_t stateVersion;
};

enum ACFlag : uint8_t {
  FLAG_SWING_VERTICAL = 1 << 0,
  FLAG_SWING_HORIZONTAL = 1 << 1,
  FLAG_TURBO = 1 << 2,
  FLAG_SLEEP = 1 << 3,
  FLAG_ECO = 1 << 4,
  FLAG_QUIET = 1 << 5,
  FLAG_LIGHT = 1 << 6,
  FLAG_XFAN = 1 << 7
};

ACState defaultState() {
  return {
    false, ACMode::COOL, 24, ACFan::AUTO,
    false, false, false, false, false, false, false, false
  };
}

bool sameText(const String& left, const char* right) {
  return right != nullptr && left.equalsIgnoreCase(right);
}

bool parseMode(const char* value, ACMode& result) {
  if (!value) return false;
  if (!strcasecmp(value, "auto")) result = ACMode::AUTO;
  else if (!strcasecmp(value, "cool")) result = ACMode::COOL;
  else if (!strcasecmp(value, "heat")) result = ACMode::HEAT;
  else if (!strcasecmp(value, "dry")) result = ACMode::DRY;
  else if (!strcasecmp(value, "fan")) result = ACMode::FAN;
  else return false;
  return true;
}

bool parseFan(const char* value, ACFan& result) {
  if (!value) return false;
  if (!strcasecmp(value, "auto")) result = ACFan::AUTO;
  else if (!strcasecmp(value, "low")) result = ACFan::LOW;
  else if (!strcasecmp(value, "medium")) result = ACFan::MEDIUM;
  else if (!strcasecmp(value, "high")) result = ACFan::HIGH;
  else return false;
  return true;
}

stdAc::opmode_t commonMode(ACMode mode) {
  switch (mode) {
    case ACMode::AUTO: return stdAc::opmode_t::kAuto;
    case ACMode::HEAT: return stdAc::opmode_t::kHeat;
    case ACMode::DRY: return stdAc::opmode_t::kDry;
    case ACMode::FAN: return stdAc::opmode_t::kFan;
    default: return stdAc::opmode_t::kCool;
  }
}

stdAc::fanspeed_t commonFan(ACFan fan) {
  switch (fan) {
    case ACFan::LOW: return stdAc::fanspeed_t::kLow;
    case ACFan::MEDIUM: return stdAc::fanspeed_t::kMedium;
    case ACFan::HIGH: return stdAc::fanspeed_t::kHigh;
    default: return stdAc::fanspeed_t::kAuto;
  }
}

stdAc::state_t commonState(
  decode_type_t protocol,
  int16_t model,
  const ACState& state
) {
  stdAc::state_t result;
  result.protocol = protocol;
  result.model = model;
  result.power = state.power;
  result.mode = commonMode(state.mode);
  result.degrees = state.temperature;
  result.celsius = true;
  result.fanspeed = commonFan(state.fan);
  result.swingv = state.swingVertical ? stdAc::swingv_t::kAuto : stdAc::swingv_t::kOff;
  result.swingh = state.swingHorizontal ? stdAc::swingh_t::kAuto : stdAc::swingh_t::kOff;
  result.quiet = state.quiet;
  result.turbo = state.turbo;
  result.econo = state.eco;
  result.light = state.light;
  result.clean = state.xFan;
  result.sleep = state.sleep ? 0 : -1;
  return result;
}

int16_t greeModel(const String& model) {
  if (sameText(model, "ybofb")) return 2;
  if (sameText(model, "yx1fsf")) return 3;
  return 1;
}

int16_t haierModel(const String& model) {
  return sameText(model, "v9014557_b") ? 2 : 1;
}

decode_type_t haierProtocol(const String& protocol) {
  if (sameText(protocol, "haier_ac")) return decode_type_t::HAIER_AC;
  if (sameText(protocol, "haier_ac160")) return decode_type_t::HAIER_AC160;
  if (sameText(protocol, "haier_ac176")) return decode_type_t::HAIER_AC176;
  return decode_type_t::HAIER_AC_YRW02;
}

bool supportedProtocol(const String& protocol) {
  return sameText(protocol, "gree") ||
    sameText(protocol, "haier_ac") ||
    sameText(protocol, "haier_ac_yrw02") ||
    sameText(protocol, "haier_ac160") ||
    sameText(protocol, "haier_ac176") ||
    sameText(protocol, "midea") ||
    sameText(protocol, "kelon168");
}

ACCapabilities capabilitiesFor(const String& protocol) {
  ACCapabilities caps = {
    true, true, true, true, true, false,
    false, false, false, false, false, false, 16, 30
  };
  if (sameText(protocol, "gree")) {
    caps.swingHorizontal = caps.turbo = caps.sleep = caps.eco = caps.light = caps.xFan = true;
  } else if (sameText(protocol, "midea")) {
    caps.turbo = caps.sleep = caps.eco = caps.quiet = caps.light = caps.xFan = true;
  } else if (sameText(protocol, "kelon168")) {
    caps.turbo = caps.sleep = caps.light = true;
    caps.maximumTemperature = 32;
  } else if (sameText(protocol, "haier_ac160")) {
    caps.turbo = caps.sleep = caps.quiet = caps.light = caps.xFan = true;
  } else if (sameText(protocol, "haier_ac176") || sameText(protocol, "haier_ac_yrw02")) {
    caps.swingHorizontal = caps.turbo = caps.sleep = caps.quiet = true;
  } else if (sameText(protocol, "haier_ac")) {
    caps.sleep = true;
  }
  return caps;
}

bool sameConfig(const ACDeviceConfig& a, const ACDeviceConfig& b) {
  return a.brand.equalsIgnoreCase(b.brand) &&
    a.protocol.equalsIgnoreCase(b.protocol) &&
    a.model.equalsIgnoreCase(b.model);
}

bool sameState(const ACState& a, const ACState& b) {
  return a.power == b.power && a.mode == b.mode &&
    a.temperature == b.temperature && a.fan == b.fan &&
    a.swingVertical == b.swingVertical &&
    a.swingHorizontal == b.swingHorizontal && a.turbo == b.turbo &&
    a.sleep == b.sleep && a.eco == b.eco && a.quiet == b.quiet &&
    a.light == b.light && a.xFan == b.xFan;
}

class ACProtocolAdapter {
 public:
  virtual ~ACProtocolAdapter() {}
  virtual bool send(
    uint8_t pin,
    const ACDeviceConfig& config,
    const ACState& state,
    const ACState& previous
  ) = 0;
};

class CommonAdapter : public ACProtocolAdapter {
 public:
  CommonAdapter(decode_type_t protocol, int16_t model)
    : protocol_(protocol), model_(model) {}

  bool send(
    uint8_t pin,
    const ACDeviceConfig&,
    const ACState& state,
    const ACState& previous
  ) override {
    IRac sender(pin);
    const stdAc::state_t desired = commonState(protocol_, model_, state);
    const stdAc::state_t prior = commonState(protocol_, model_, previous);
    return sender.sendAc(desired, &prior);
  }

 private:
  decode_type_t protocol_;
  int16_t model_;
};

class HisenseAdapter : public ACProtocolAdapter {
 public:
  bool send(
    uint8_t pin,
    const ACDeviceConfig&,
    const ACState& state,
    const ACState& previous
  ) override {
    IRKelon168Ac sender(pin);
    sender.begin();
    sender.setModel(kelon168_ac_remote_model_t::DG11R201);
    sender.setPower(state.power);
    sender.setMode(IRKelon168Ac::convertMode(commonMode(state.mode)));
    sender.setTemp(state.temperature);
    sender.setFan(IRKelon168Ac::convertFan(commonFan(state.fan)));
    sender.setSwing(state.swingVertical);
    sender.setSuper(state.turbo);
    sender.setSleep(state.sleep);
    sender.setLight(state.light);
    if (state.power != previous.power) sender.setCommand(kKelon168CommandPower);
    else if (state.mode != previous.mode) sender.setCommand(kKelon168CommandMode);
    else if (state.temperature != previous.temperature) sender.setCommand(kKelon168CommandTemp);
    else if (state.fan != previous.fan) sender.setCommand(kKelon168CommandFanSpeed);
    else if (state.swingVertical != previous.swingVertical) sender.setCommand(kKelon168CommandSwing);
    else if (state.turbo != previous.turbo) sender.setCommand(kKelon168CommandSuper);
    else if (state.sleep != previous.sleep) sender.setCommand(kKelon168CommandSleep);
    else if (state.light != previous.light) sender.setCommand(kKelon168CommandLight);
    else sender.setCommand(kKelon168CommandTemp);
    sender.send();
    return true;
  }
};

bool sendOnPin(
  uint8_t pin,
  const ACDeviceConfig& config,
  const ACState& state,
  const ACState& previous
) {
  if (sameText(config.protocol, "gree")) {
    CommonAdapter adapter(decode_type_t::GREE, greeModel(config.model));
    return adapter.send(pin, config, state, previous);
  }
  if (sameText(config.protocol, "midea")) {
    CommonAdapter adapter(decode_type_t::MIDEA, -1);
    return adapter.send(pin, config, state, previous);
  }
  if (sameText(config.protocol, "kelon168")) {
    HisenseAdapter adapter;
    return adapter.send(pin, config, state, previous);
  }
  CommonAdapter adapter(haierProtocol(config.protocol), haierModel(config.model));
  return adapter.send(pin, config, state, previous);
}

bool readBoolean(
  JsonObjectConst patch,
  const char* name,
  bool supported,
  bool& destination,
  String& error
) {
  if (!patch.containsKey(name)) return true;
  if (!supported) {
    error = String(name) + " is not supported by this protocol";
    return false;
  }
  if (!patch[name].is<bool>()) {
    error = String(name) + " must be a boolean";
    return false;
  }
  destination = patch[name].as<bool>();
  return true;
}

}  // namespace

const char* acModeName(ACMode mode) {
  switch (mode) {
    case ACMode::AUTO: return "auto";
    case ACMode::HEAT: return "heat";
    case ACMode::DRY: return "dry";
    case ACMode::FAN: return "fan";
    default: return "cool";
  }
}

const char* acFanName(ACFan fan) {
  switch (fan) {
    case ACFan::LOW: return "low";
    case ACFan::MEDIUM: return "medium";
    case ACFan::HIGH: return "high";
    default: return "auto";
  }
}

ACController::ACController(const uint8_t* outputPins, size_t outputCount)
  : outputPins_(outputPins), outputCount_(outputCount), configured_(false),
    beforeTransmission_(nullptr), afterTransmission_(nullptr) {
  runtime_.state = defaultState();
  runtime_.stateVersion = 0;
  runtime_.updatedAt = 0;
}

void ACController::begin(
  ACTransmissionHook beforeTransmission,
  ACTransmissionHook afterTransmission
) {
  beforeTransmission_ = beforeTransmission;
  afterTransmission_ = afterTransmission;
  loadState();
}

bool ACController::isConfigured() const { return configured_; }
const ACDeviceConfig& ACController::config() const { return config_; }
const ACDeviceRuntime& ACController::runtime() const { return runtime_; }

ACCapabilities ACController::capabilities() const {
  return capabilitiesFor(config_.protocol);
}

void ACController::loadState() {
  runtime_.state = defaultState();
  runtime_.stateVersion = 0;
  runtime_.updatedAt = 0;
  preferences_.begin("ac-state", true);
  config_.brand = preferences_.getString("brand", "");
  config_.protocol = preferences_.getString("protocol", "");
  config_.model = preferences_.getString("model", "default");
  PersistedACState saved = {};
  const size_t bytes = preferences_.getBytes("state", &saved, sizeof(saved));
  preferences_.end();
  configured_ = config_.brand.length() > 0 && supportedProtocol(config_.protocol);
  if (!configured_ || bytes != sizeof(saved) || saved.schema != AC_PERSISTENCE_SCHEMA ||
      saved.mode > static_cast<uint8_t>(ACMode::FAN) ||
      saved.fan > static_cast<uint8_t>(ACFan::HIGH)) return;
  const ACCapabilities caps = capabilities();
  if (saved.temperature < caps.minimumTemperature || saved.temperature > caps.maximumTemperature) return;
  ACState& state = runtime_.state;
  state.power = saved.power;
  state.mode = static_cast<ACMode>(saved.mode);
  state.temperature = saved.temperature;
  state.fan = static_cast<ACFan>(saved.fan);
  state.swingVertical = saved.flags & FLAG_SWING_VERTICAL;
  state.swingHorizontal = saved.flags & FLAG_SWING_HORIZONTAL;
  state.turbo = saved.flags & FLAG_TURBO;
  state.sleep = saved.flags & FLAG_SLEEP;
  state.eco = saved.flags & FLAG_ECO;
  state.quiet = saved.flags & FLAG_QUIET;
  state.light = saved.flags & FLAG_LIGHT;
  state.xFan = saved.flags & FLAG_XFAN;
  runtime_.stateVersion = saved.stateVersion;
}

void ACController::saveState() {
  const ACState& state = runtime_.state;
  PersistedACState saved = {
    AC_PERSISTENCE_SCHEMA, static_cast<uint8_t>(state.power),
    static_cast<uint8_t>(state.mode), state.temperature,
    static_cast<uint8_t>(state.fan),
    static_cast<uint8_t>(
      (state.swingVertical ? FLAG_SWING_VERTICAL : 0) |
      (state.swingHorizontal ? FLAG_SWING_HORIZONTAL : 0) |
      (state.turbo ? FLAG_TURBO : 0) | (state.sleep ? FLAG_SLEEP : 0) |
      (state.eco ? FLAG_ECO : 0) | (state.quiet ? FLAG_QUIET : 0) |
      (state.light ? FLAG_LIGHT : 0) | (state.xFan ? FLAG_XFAN : 0)
    ),
    runtime_.stateVersion
  };
  preferences_.begin("ac-state", false);
  preferences_.putString("brand", config_.brand);
  preferences_.putString("protocol", config_.protocol);
  preferences_.putString("model", config_.model);
  preferences_.putBytes("state", &saved, sizeof(saved));
  preferences_.end();
}

bool ACController::validateAndMerge(
  const ACDeviceConfig& config,
  JsonObjectConst patch,
  ACState& candidate,
  String& error
) const {
  const ACCapabilities caps = capabilitiesFor(config.protocol);
  if (!readBoolean(patch, "power", caps.power, candidate.power, error) ||
      !readBoolean(patch, "swing_vertical", caps.swingVertical, candidate.swingVertical, error) ||
      !readBoolean(patch, "swing_horizontal", caps.swingHorizontal, candidate.swingHorizontal, error) ||
      !readBoolean(patch, "turbo", caps.turbo, candidate.turbo, error) ||
      !readBoolean(patch, "sleep", caps.sleep, candidate.sleep, error) ||
      !readBoolean(patch, "eco", caps.eco, candidate.eco, error) ||
      !readBoolean(patch, "quiet", caps.quiet, candidate.quiet, error) ||
      !readBoolean(patch, "light", caps.light, candidate.light, error) ||
      !readBoolean(patch, "x_fan", caps.xFan, candidate.xFan, error)) return false;
  if (patch.containsKey("temperature")) {
    if (!patch["temperature"].is<int>()) { error = "temperature must be an integer"; return false; }
    const int value = patch["temperature"].as<int>();
    if (value < caps.minimumTemperature || value > caps.maximumTemperature) {
      error = "temperature is outside this protocol's supported range";
      return false;
    }
    candidate.temperature = value;
  }
  if (patch.containsKey("mode") &&
      (!patch["mode"].is<const char*>() ||
       !parseMode(patch["mode"].as<const char*>(), candidate.mode))) {
    error = "mode must be auto, cool, heat, dry, or fan";
    return false;
  }
  if (patch.containsKey("fan") &&
      (!patch["fan"].is<const char*>() ||
       !parseFan(patch["fan"].as<const char*>(), candidate.fan))) {
    error = "fan must be auto, low, medium, or high";
    return false;
  }
  return true;
}

bool ACController::sendState(
  const ACDeviceConfig& config,
  const ACState& state,
  const ACState& previous,
  String& error
) {
  if (!supportedProtocol(config.protocol)) {
    error = String("unsupported AC protocol: ") + config.protocol;
    return false;
  }
  if (beforeTransmission_) beforeTransmission_();
  bool success = outputCount_ > 0;
  for (size_t i = 0; i < outputCount_ && success; i++) {
    success = sendOnPin(outputPins_[i], config, state, previous);
    digitalWrite(outputPins_[i], LOW);
    if (i + 1 < outputCount_) delay(5);
  }
  if (afterTransmission_) afterTransmission_();
  if (!success) error = "AC protocol library rejected the state";
  return success;
}

bool ACController::applyPatch(
  const ACDeviceConfig& config,
  JsonObjectConst patch,
  uint32_t requestedVersion,
  bool hasRequestedVersion,
  String& error
) {
  if (!supportedProtocol(config.protocol) || config.brand.length() == 0 || config.model.length() == 0) {
    error = "brand, protocol, and model must describe a supported AC";
    return false;
  }
  if (hasRequestedVersion && requestedVersion < runtime_.stateVersion) {
    error = "state_version is older than the ESP32 state";
    return false;
  }
  const bool configChanged = !configured_ || !sameConfig(config_, config);
  ACState candidate = configChanged ? defaultState() : runtime_.state;
  if (!validateAndMerge(config, patch, candidate, error)) return false;
  if (!configChanged && sameState(candidate, runtime_.state)) return true;
  if (runtime_.stateVersion == UINT32_MAX) { error = "state_version is exhausted"; return false; }
  if (!sendState(config, candidate, runtime_.state, error)) return false;
  config_ = config;
  configured_ = true;
  runtime_.state = candidate;
  runtime_.stateVersion++;
  if (hasRequestedVersion && requestedVersion > runtime_.stateVersion) runtime_.stateVersion = requestedVersion;
  runtime_.updatedAt = millis();
  saveState();
  return true;
}

void ACController::writeState(JsonObject target, const ACState& state) const {
  target["power"] = state.power;
  target["mode"] = acModeName(state.mode);
  target["temperature"] = state.temperature;
  target["fan"] = acFanName(state.fan);
  target["swing_vertical"] = state.swingVertical;
  target["swing_horizontal"] = state.swingHorizontal;
  target["turbo"] = state.turbo;
  target["sleep"] = state.sleep;
  target["eco"] = state.eco;
  target["quiet"] = state.quiet;
  target["light"] = state.light;
  target["x_fan"] = state.xFan;
}

void ACController::writeController(JsonObject target) const {
  target["brand"] = config_.brand;
  target["protocol"] = config_.protocol;
  target["model"] = config_.model;
  target["state_version"] = runtime_.stateVersion;
  target["updated_at"] = runtime_.updatedAt;
  JsonObject state = target["state"].to<JsonObject>();
  writeState(state, runtime_.state);
}

void ACController::writeCapabilities(JsonObject target) const {
  const ACCapabilities caps = capabilities();
  target["power"] = caps.power;
  target["temperature"] = caps.temperature;
  target["temperature_min"] = caps.minimumTemperature;
  target["temperature_max"] = caps.maximumTemperature;
  target["mode"] = caps.mode;
  target["fan"] = caps.fan;
  target["swing_vertical"] = caps.swingVertical;
  target["swing_horizontal"] = caps.swingHorizontal;
  target["turbo"] = caps.turbo;
  target["sleep"] = caps.sleep;
  target["eco"] = caps.eco;
  target["quiet"] = caps.quiet;
  target["light"] = caps.light;
  target["x_fan"] = caps.xFan;
}
