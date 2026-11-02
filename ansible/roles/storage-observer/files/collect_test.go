package main

import (
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestMetricNamingAndMissingSeries(t *testing.T) {
	cases := []struct {
		body string
		want float64
	}{
		{`api_s3_request_counter{method="GET"} 3
api_s3_request_counter{method="PUT"} 2`, 5},
		{"api_s3_request_counter_total 4\n", 4},
		{"# HELP api_s3_request_counter requests\n", 0},
		{"api_s3_request_counter 3\napi_s3_request_counter_total 999\n", 3},
	}
	for _, c := range cases {
		got, e := metricSum([]byte(c.body), "api_s3_request_counter")
		if e != nil || got != c.want {
			t.Fatal(got, e)
		}
	}
	for _, body := range []string{"api_s3_request_counter NaN", "api_s3_request_counter -1", "api_s3_request_counter +Inf"} {
		if _, e := metricSum([]byte(body), "api_s3_request_counter"); e == nil {
			t.Fatal("accepted bad counter")
		}
	}
}
func TestNumericAllowlist(t *testing.T) {
	raw := map[string]any{"count": float64(3), "secret": "NEVER_EXPORT"}
	clean, e := selected(raw, []string{"count"})
	if e != nil || len(clean) != 1 {
		t.Fatal(clean, e)
	}
	for _, v := range []any{nil, "3", float64(-1), math.NaN(), 1.5} {
		raw["count"] = v
		if _, e := selected(raw, []string{"count"}); e == nil {
			t.Fatal("accepted invalid aggregate")
		}
	}
}

type transport struct{ target *url.URL }

func (t transport) RoundTrip(r *http.Request) (*http.Response, error) {
	r.URL.Scheme = t.target.Scheme
	r.URL.Host = t.target.Host
	return http.DefaultTransport.RoundTrip(r)
}
func TestGarageAuthenticatedBoundedAggregateOnly(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer fixture-token" {
			t.Error("missing scoped auth")
		}
		switch r.URL.Path {
		case "/v2/GetClusterStatistics":
			w.Write([]byte(`{"bucketCount":1,"totalObjectCount":2,"totalObjectBytes":3,"freeform":"NEVER_EXPORT"}`))
		case "/v2/GetClusterHealth":
			w.Write([]byte(`{"status":"healthy"}`))
		case "/metrics":
			w.Write([]byte("api_s3_request_counter 4\n"))
		default:
			t.Error("unexpected endpoint")
		}
	}))
	defer server.Close()
	target, _ := url.Parse(server.URL)
	sample, e := garage(&http.Client{Transport: transport{target}}, "fixture-token")
	if e != nil || sample.Values["totalObjectCount"] != 2 || sample.Health != "healthy" {
		t.Fatal(sample, e)
	}
	if len(sample.Values) != 5 {
		t.Fatal("freeform leaked")
	}
	huge := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(strings.Repeat("x", 1048577))) }))
	defer huge.Close()
	target, _ = url.Parse(huge.URL)
	if _, e = get(&http.Client{Transport: transport{target}}, "/metrics", "fixture-token"); e == nil {
		t.Fatal("accepted oversize reply")
	}
}
