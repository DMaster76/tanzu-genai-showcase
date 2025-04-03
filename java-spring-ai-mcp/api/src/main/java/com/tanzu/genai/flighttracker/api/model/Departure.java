package com.tanzu.genai.flighttracker.api.model;

import lombok.Data;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Model class for Departure information.
 */
@Data
public class Departure {
    private String airport;
    private String timezone;
    private String iata;
    private String icao;
    private String terminal;
    private String gate;
    private Integer delay;
    private String scheduled;
    private String estimated;
    private String actual;
    
    @JsonProperty("iata_code")
    private String iataCode;
    
    @JsonProperty("icao_code")
    private String icaoCode;
}
