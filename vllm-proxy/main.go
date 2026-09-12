package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	activeRequests = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "vllm_proxy_active_requests",
		Help: "Number of active requests currently being proxied to vLLM",
	})
)

func init() {
	prometheus.MustRegister(activeRequests)
}

// waitForReady polls the target's /health endpoint until it returns 200 OK.
func waitForReady(targetURL string) error {
	healthURL := targetURL + "/health"
	client := &http.Client{Timeout: 2 * time.Second}

	for {
		resp, err := client.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			resp.Body.Close()
			return nil
		}
		if resp != nil {
			resp.Body.Close()
		}
		log.Printf("Target %s not ready, waiting...", healthURL)
		time.Sleep(5 * time.Second)
	}
}

func main() {
	targetStr := os.Getenv("TARGET_URL")
	if targetStr == "" {
		targetStr = "http://vllm-server.vllm.svc.cluster.local:8000"
	}
	target, err := url.Parse(targetStr)
	if err != nil {
		log.Fatalf("Invalid TARGET_URL: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	// Custom Transport to handle potential long-running connections (e.g. streaming)
	proxy.Transport = &http.Transport{
		ResponseHeaderTimeout: 30 * time.Minute,
		IdleConnTimeout:       30 * time.Minute,
	}

	mux := http.NewServeMux()

	// Prometheus metrics endpoint
	mux.Handle("/metrics", promhttp.Handler())

	// Proxy all other requests
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		activeRequests.Inc()
		defer activeRequests.Dec()

		log.Printf("Received request for %s", r.URL.Path)

		// Block until the target is healthy
		// (This holds the connection open while KEDA scales vLLM from 0 -> 1)
		err := waitForReady(targetStr)
		if err != nil {
			http.Error(w, "Failed to reach backend", http.StatusBadGateway)
			return
		}

		proxy.ServeHTTP(w, r)
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Proxy listening on :%s, targeting %s", port, targetStr)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}
