#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

// Small, versioned datagrams; independent of ESPHome for native protocol tests.
namespace controller_events {

constexpr size_t MAX_PACKET_SIZE = 128;

// One independent instance per contact, shared by real and simulated trips.
// Unsigned subtraction keeps the one-second interval correct at millis wrap.
class SensorTriggerLimiter {
 public:
  bool accept(uint32_t now) {
    if (has_triggered_ && static_cast<uint32_t>(now - last_trigger_) < 1000U)
      return false;
    has_triggered_ = true;
    last_trigger_ = now;
    return true;
  }

 private:
  bool has_triggered_{false};
  uint32_t last_trigger_{0};
};

struct Event {
  std::string source;
  std::string event;
  int item;
  std::string reason;
};

inline bool valid_event(const Event &message) {
  if (message.source.empty() || message.source.size() > 63 || message.item < 1 || message.item > 4)
    return false;
  for (char c : message.source) {
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-'))
      return false;
  }
  if (message.event == "sequence.ready")
    return message.reason == "cooldown_finished" || message.reason == "stopped";
  return message.reason.empty() &&
         (message.event == "sensor.triggered" || message.event == "sensor.released" ||
          message.event == "sequence.started" || message.event == "sequence.cooling_down");
}

inline std::string encode(const Event &message) {
  if (!valid_event(message))
    return {};
  return "HC1|" + message.source + "|" + message.event + "|" + std::to_string(message.item) + "|" +
         message.reason;
}

inline bool decode(const std::string &packet, Event &message) {
  if (packet.size() > MAX_PACKET_SIZE || packet.compare(0, 4, "HC1|") != 0)
    return false;
  const auto source_end = packet.find('|', 4);
  if (source_end == std::string::npos)
    return false;
  const auto event_end = packet.find('|', source_end + 1);
  if (event_end == std::string::npos || event_end + 2 >= packet.size() || packet[event_end + 2] != '|')
    return false;
  Event candidate{packet.substr(4, source_end - 4),
                  packet.substr(source_end + 1, event_end - source_end - 1),
                  packet[event_end + 1] - '0', packet.substr(event_end + 3)};
  if (!valid_event(candidate))
    return false;
  message = candidate;
  return true;
}

}  // namespace controller_events
