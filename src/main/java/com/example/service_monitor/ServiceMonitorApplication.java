package com.example.service_monitor;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ServiceMonitorApplication {

    public static void main(String[] args) {

        SpringApplication.run(ServiceMonitorApplication.class, args);
        System.out.println("System is running");
    }

}
