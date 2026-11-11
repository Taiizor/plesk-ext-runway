// Minimal Go web app for testing Runway (Plesk extension).
// Build: go build -o bin/app .    Start: ./bin/app
package main

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"runtime"
)

func main() {
	host := os.Getenv("HOST")
	if host == "" {
		host = "127.0.0.1"
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	addr := net.JoinHostPort(host, port)

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "Hello from Go %s on %s (%s via %s)\n", runtime.Version(), addr, r.Host, r.Header.Get("X-Forwarded-Proto"))
	})
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})

	// Unix socket mode (recommended on shared servers): Runway sets RUNWAY_SOCKET.
	if sock := os.Getenv("RUNWAY_SOCKET"); sock != "" {
		ln, err := net.Listen("unix", sock)
		if err != nil {
			log.Fatal(err)
		}
		addr = "unix:" + sock // shown by the handler above
		log.Printf("listening on %s", addr)
		log.Fatal(http.Serve(ln, nil))
	}

	log.Printf("listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}
