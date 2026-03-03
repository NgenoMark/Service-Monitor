package com.example.service_monitor;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

@RestController
@RequestMapping("/sim")
public class SimulationController {

    @GetMapping("/error")
    public ResponseEntity<Map<String, Object>> alwaysError() {
        Map<String, Object> payload = new HashMap<>();
        payload.put("status", 500);
        payload.put("message", "simulated error");
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(payload);
    }

    @GetMapping("/flaky")
    public ResponseEntity<Map<String, Object>> flaky() {
        boolean fail = ThreadLocalRandom.current().nextBoolean();
        Map<String, Object> payload = new HashMap<>();

        if (fail) {
            payload.put("status", 500);
            payload.put("message", "simulated intermittent failure");
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(payload);
        }

        payload.put("status", 200);
        payload.put("message", "ok");
        return ResponseEntity.ok(payload);
    }
}
