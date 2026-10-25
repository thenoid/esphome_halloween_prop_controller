#include "packages/controller-events.h"

#include <cassert>
#include <iostream>
#include <vector>

int main() {
  // The first trip is prompt even at boot. Rejected trips do not restart the
  // interval, and each sensor has an independent limit.
  controller_events::SensorTriggerLimiter first, second;
  assert(first.accept(0));
  assert(!first.accept(0));
  assert(!first.accept(50));
  assert(!first.accept(999));
  assert(second.accept(50));
  assert(first.accept(1000));
  assert(!first.accept(1999));
  assert(first.accept(2000));
  assert(second.accept(1050));
  controller_events::SensorTriggerLimiter rollover;
  assert(rollover.accept(UINT32_MAX - 499));
  assert(!rollover.accept(499));
  assert(rollover.accept(500));
  std::cout << "Sensor trip limiter: prompt first trip, per-sensor interval, exact boundary, and clock rollover passed.\n";

  using controller_events::Event;
  const std::vector<Event> events{
      {"prop-controller-1", "sensor.triggered", 2, ""},
      {"prop-controller-3", "sensor.released", 4, ""},
      {"prop-controller-2", "sequence.started", 1, ""},
      {"prop-controller-2", "sequence.cooling_down", 1, ""},
      {"prop-controller-2", "sequence.ready", 1, "cooldown_finished"},
      {"prop-controller-2", "sequence.ready", 1, "stopped"},
      {std::string(63, 'a'), "sequence.ready", 4, "cooldown_finished"},
  };
  for (const auto &sent : events) {
    const auto packet = controller_events::encode(sent);
    assert(!packet.empty() && packet.size() <= controller_events::MAX_PACKET_SIZE);
    Event received;
    assert(controller_events::decode(packet, received));
    assert(received.source == sent.source && received.event == sent.event);
    assert(received.item == sent.item && received.reason == sent.reason);
  }
  assert(controller_events::encode(events[0]) == "HC1|prop-controller-1|sensor.triggered|2|");

  // Unrelated UDP traffic, unsupported versions/events, corrupt field lengths,
  // and invalid sequence reasons must never reach a controller's prop rules.
  const std::vector<std::string> invalid{
      "", "HC1", "HC1|", "HC1|prop-controller-1", "random UDP traffic",
      "HC2|prop-controller-1|sensor.triggered|2|",
      "HC1||sensor.triggered|2|", "HC1|bad source|sensor.triggered|2|",
      "HC1|bad\nsource|sensor.triggered|2|", "HC1|prop-controller-1|relay.on|2|",
      "HC1|prop-controller-1|sensor.triggered|0|",
      "HC1|prop-controller-1|sensor.triggered|5|",
      "HC1|prop-controller-1|sensor.triggered|-1|",
      "HC1|prop-controller-1|sensor.triggered|12|",
      "HC1|prop-controller-1|sensor.triggered|x|",
      "HC1|prop-controller-1|sensor.triggered|2",
      "HC1|prop-controller-1|sensor.triggered|2|stopped",
      "HC1|prop-controller-1|sensor.triggered|2||",
      "HC1|prop-controller-1|sequence.ready|2|",
      "HC1|prop-controller-1|sequence.ready|2|unknown",
      "HC1|prop-controller-1|sequence.ready|2|stopped|extra",
      "HC1|" + std::string(64, 'a') + "|sensor.triggered|2|",
      std::string(129, 'x'),
      std::string("HC1|node\0name|sensor.triggered|2|", 31),
  };
  for (const auto &packet : invalid) {
    Event received{"unchanged", "sequence.ready", 1, "stopped"};
    assert(!controller_events::decode(packet, received));
    assert(received.source == "unchanged");
  }
  assert(controller_events::encode({"prop-controller-1", "sequence.started", 2, "stopped"}).empty());
  std::cout << "Controller event protocol: round trips and malformed packet rejection passed.\n";
}
