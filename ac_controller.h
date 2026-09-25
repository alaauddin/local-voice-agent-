#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>

enum class ACMode : uint8_t { AUTO, COOL, HEAT, DRY, FAN };
enum class ACFan : uint8_t { AUTO, LOW, MEDIUM, HIGH };

struct ACState {
  bool power;
  ACMode mode;
  uint8_t temperature;
  ACFan fan;
  bool swingVertical;
  bool swingHorizontal;
  bool turbo;
  bool sleep;
  bool eco;
  bool quiet;
  bool light;
  bool xFan;
};

struct ACDeviceConfig {
  String brand;
  String protocol;
  String model;
};

struct ACCapabilities {
  bool power;
  bool temperature;
  bool mode;
  bool fan;
  bool swingVertical;
  bool swingHorizontal;
  bool turbo;
  bool sleep;
  bool eco;
  bool quiet;
  bool light;
  bool xFan;
  uint8_t minimumTemperature;
  uint8_t maximumTemperature;
};

struct ACDeviceRuntime {
  ACState state;
  uint32_t stateVersion;
  uint32_t updatedAt;
};

typedef void (*ACTransmissionHook)();

class ACController {
 public:
  ACController(const uint8_t* outputPins, size_t outputCount);

  void begin(
    ACTransmissionHook beforeTransmission,
    ACTransmissionHook afterTransmission
  );

  bool isConfigured() const;
  const ACDeviceConfig& config() const;
  const ACDeviceRuntime& runtime() const;
  ACCapabilities capabilities() const;

  bool applyPatch(
    const ACDeviceConfig& config,
    JsonObjectConst patch,
    uint32_t requestedVersion,
    bool hasRequestedVersion,
    String& error
  );

  void writeState(JsonObject target, const ACState& state) const;
  void writeController(JsonObject target) const;
  void writeCapabilities(JsonObject target) const;

 private:
  const uint8_t* outputPins_;
  size_t outputCount_;
  ACDeviceConfig config_;
  ACDeviceRuntime runtime_;
  bool configured_;
  ACTransmissionHook beforeTransmission_;
  ACTransmissionHook afterTransmission_;
  Preferences preferences_;

  void loadState();
  void saveState();
  bool validateAndMerge(
    const ACDeviceConfig& config,
    JsonObjectConst patch,
    ACState& candidate,
    String& error
  ) const;
  bool sendState(
    const ACDeviceConfig& config,
    const ACState& state,
    const ACState& previous,
    String& error
  );
};

const char* acModeName(ACMode mode);
const char* acFanName(ACFan fan);
