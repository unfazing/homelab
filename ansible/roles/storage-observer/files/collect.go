// Fixed aggregate-only collector. No HTTP listener, Docker socket or app data.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Sample struct {
	CheckedAt int64              `json:"checked_at"`
	Values    map[string]float64 `json:"values"`
	ResetID   string             `json:"reset_id,omitempty"`
	Health    string             `json:"health,omitempty"`
	Error     string             `json:"error,omitempty"`
}
type Snapshot struct {
	Version    int    `json:"version"`
	Garage     Sample `json:"garage"`
	PostgreSQL Sample `json:"postgresql"`
}
type Config struct {
	Databases []string `json:"databases"`
}

func number(v any) (float64, error) {
	n, ok := v.(float64)
	if !ok || math.IsNaN(n) || math.IsInf(n, 0) || n < 0 || n != math.Trunc(n) || n > 9e15 {
		return 0, errors.New("invalid aggregate")
	}
	return n, nil
}
func selected(raw map[string]any, names []string) (map[string]float64, error) {
	result := map[string]float64{}
	for _, k := range names {
		v, e := number(raw[k])
		if e != nil {
			return nil, e
		}
		result[k] = v
	}
	return result, nil
}
func get(client *http.Client, path, token string) ([]byte, error) {
	req, e := http.NewRequest("GET", "http://garage:3903"+path, nil)
	if e != nil {
		return nil, e
	}
	req.Header.Set("Authorization", "Bearer "+token)
	res, e := client.Do(req)
	if e != nil {
		return nil, e
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, errors.New("endpoint unavailable")
	}
	body, e := io.ReadAll(io.LimitReader(res.Body, 1048577))
	if len(body) > 1048576 {
		return nil, errors.New("oversize response")
	}
	return body, e
}
func metricSum(body []byte, name string) (float64, error) {
	// Prefer a single exposition naming variant; never sum both base and _total.
	for _, target := range []string{name, name + "_total"} {
		total := 0.0
		found := false
		for _, line := range strings.Split(string(body), "\n") {
			if !(strings.HasPrefix(line, target+" ") || strings.HasPrefix(line, target+"{")) {
				continue
			}
			end := len(target)
			if line[end] == '{' {
				x := strings.LastIndex(line, "}")
				if x < end {
					return 0, errors.New("bad metric")
				}
				end = x + 1
			}
			fields := strings.Fields(line[end:])
			if len(fields) < 1 {
				return 0, errors.New("bad metric")
			}
			n, e := strconv.ParseFloat(fields[0], 64)
			if e != nil || math.IsNaN(n) || math.IsInf(n, 0) || n < 0 {
				return 0, errors.New("bad counter")
			}
			total += n
			found = true
		}
		if found {
			return total, nil
		}
	}
	// Garage does not expose a labeled family until its first request/error.
	return 0, nil
}
func garage(client *http.Client, token string) (Sample, error) {
	body, e := get(client, "/v2/GetClusterStatistics", token)
	if e != nil {
		return Sample{}, e
	}
	var raw map[string]any
	if e = json.Unmarshal(body, &raw); e != nil {
		return Sample{}, e
	}
	values, e := selected(raw, []string{"bucketCount", "totalObjectCount", "totalObjectBytes"})
	if e != nil {
		return Sample{}, e
	}
	body, e = get(client, "/v2/GetClusterHealth", token)
	if e != nil {
		return Sample{}, e
	}
	var health struct {
		Status string `json:"status"`
	}
	if e = json.Unmarshal(body, &health); e != nil {
		return Sample{}, e
	}
	if health.Status != "healthy" && health.Status != "degraded" && health.Status != "unavailable" {
		return Sample{}, errors.New("unknown health")
	}
	body, e = get(client, "/metrics", token)
	if e != nil {
		return Sample{}, e
	}
	for _, k := range []string{"api_s3_request_counter", "api_s3_error_counter"} {
		v, e := metricSum(body, k)
		if e != nil {
			return Sample{}, e
		}
		values[k] = v
	}
	return Sample{CheckedAt: time.Now().Unix(), Values: values, Health: health.Status}, nil
}
func query(database string) (map[string]any, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "psql", "--no-psqlrc", "--set=ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--host=postgresql", "--username=homelab_monitor", "--dbname="+database, "--command=SELECT homelab_monitor.snapshot();")
	cmd.Env = append(os.Environ(), "PGPASSFILE=/run/secrets/pgpass", "PGSSLMODE=disable", "PGCONNECT_TIMEOUT=3")
	// Output is bounded independently of the safe fixed SQL.
	out := &boundedWriter{}
	cmd.Stdout = out
	cmd.Stderr = io.Discard
	if e := cmd.Run(); e != nil {
		return nil, e
	}
	var raw map[string]any
	e := json.Unmarshal(out.data, &raw)
	return raw, e
}

type boundedWriter struct{ data []byte }

func (w *boundedWriter) Write(p []byte) (int, error) {
	if len(w.data)+len(p) > 16384 {
		return 0, errors.New("oversize SQL result")
	}
	w.data = append(w.data, p...)
	return len(p), nil
}
func postgres(config Config) (Sample, error) {
	raw, e := query("postgres")
	if e != nil {
		return Sample{}, e
	}
	values, e := selected(raw, []string{"databases", "database_bytes", "transactions", "connections", "active", "blocked", "connection_limit", "server_start"})
	if e != nil {
		return Sample{}, e
	}
	reset, ok := raw["reset_id"].(string)
	if !ok || !regexp.MustCompile(`^[a-f0-9]{32}$`).MatchString(reset) {
		return Sample{}, errors.New("invalid reset marker")
	}
	values["tables"] = 0
	for _, database := range config.Databases {
		r, e := query(database)
		if e != nil {
			return Sample{}, e
		}
		v, e := number(r["tables"])
		if e != nil {
			return Sample{}, e
		}
		values["tables"] += v
	}
	return Sample{CheckedAt: time.Now().Unix(), Values: values, ResetID: reset}, nil
}
func save(snapshot Snapshot, path string) error {
	data, e := json.Marshal(snapshot)
	if e != nil {
		return e
	}
	file, e := os.CreateTemp(filepath.Dir(path), ".snapshot-")
	if e != nil {
		return e
	}
	name := file.Name()
	defer os.Remove(name)
	if e = file.Chmod(0640); e == nil {
		_, e = file.Write(data)
	}
	if e == nil {
		e = file.Sync()
	}
	closeErr := file.Close()
	if e == nil {
		e = closeErr
	}
	if e == nil {
		e = os.Rename(name, path)
	}
	return e
}
func main() {
	if len(os.Args) == 2 && os.Args[1] == "--check" {
		info, e := os.Stat("/output/snapshot.json")
		if e != nil || time.Since(info.ModTime()) > 180*time.Second {
			os.Exit(1)
		}
		return
	}
	var config Config
	data, e := os.ReadFile("/config/config.json")
	if e == nil {
		e = json.Unmarshal(data, &config)
	}
	valid := regexp.MustCompile(`^[a-z][a-z0-9_]{0,46}$`)
	if e != nil || len(config.Databases) == 0 || len(config.Databases) > 32 {
		os.Exit(1)
	}
	for _, name := range config.Databases {
		if !valid.MatchString(name) {
			os.Exit(1)
		}
	}
	data, e = os.ReadFile("/run/secrets/garage-token")
	if e != nil {
		os.Exit(1)
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		os.Exit(1)
	}
	client := &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return errors.New("redirect denied") }}
	snapshot := Snapshot{Version: 1}
	// Values are sampled anew on start; never hydrate an untrusted cache.
	for {
		if sample, e := garage(client, token); e == nil {
			snapshot.Garage = sample
		} else {
			snapshot.Garage.Error = "collection failed"
		}
		if sample, e := postgres(config); e == nil {
			snapshot.PostgreSQL = sample
		} else {
			snapshot.PostgreSQL.Error = "collection failed"
		}
		if e := save(snapshot, "/output/snapshot.json"); e != nil {
			fmt.Fprintln(os.Stderr, "Snapshot write failed")
		}
		time.Sleep(60 * time.Second)
	}
}
