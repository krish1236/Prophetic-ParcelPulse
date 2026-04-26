"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// OpenFreeMap is a free, key-less MapLibre tile service. Positron is a clean
// light-grey style that lets the parcel data dominate the visual field.
// Phase 11 swaps to a Multnomah-clipped PMTiles archive on R2.
const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

const AXIS_COLOR: Record<string, string> = {
  permit: "#f59e0b",
  flood: "#0ea5e9",
  zoning: "#a855f7",
  ownership: "#10b981",
  market: "#f43f5e",
};

const PORTLAND_CENTER: [number, number] = [-122.66, 45.535];
const PORTLAND_ZOOM = 11;

export function ParcelMap({
  watchlistId,
  className,
}: {
  watchlistId: string;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE_URL,
      center: PORTLAND_CENTER,
      zoom: PORTLAND_ZOOM,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    const parcelsUrl = `${API_BASE}/feed/${watchlistId}.geojson?layer=parcels`;
    const alertsUrl = `${API_BASE}/feed/${watchlistId}.geojson?layer=alerts`;

    map.on("load", () => {
      map.addSource("parcels", { type: "geojson", data: parcelsUrl });
      map.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: "parcels",
        paint: { "fill-color": "#3b82f6", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: "parcels-outline",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#3b82f6", "line-width": 1.5 },
      });

      map.addSource("alerts", { type: "geojson", data: alertsUrl });
      map.addLayer({
        id: "alerts-circle",
        type: "circle",
        source: "alerts",
        paint: {
          "circle-color": [
            "match",
            ["get", "axis"],
            "permit", AXIS_COLOR.permit,
            "flood", AXIS_COLOR.flood,
            "zoning", AXIS_COLOR.zoning,
            "ownership", AXIS_COLOR.ownership,
            "market", AXIS_COLOR.market,
            "#9ca3af",
          ],
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["get", "materiality_score"],
            0, 5,
            100, 16,
          ],
          "circle-opacity": 0.9,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#0a0a0a",
        },
      });

      // Fit bounds to parcels — fetch the GeoJSON ourselves so we don't have
      // to reach into MapLibre source internals.
      void fetch(parcelsUrl)
        .then((r) => r.json())
        .then((fc: GeoJSON.FeatureCollection) => {
          const bounds = computeBounds(fc);
          if (bounds && mapRef.current) {
            mapRef.current.fitBounds(bounds, {
              padding: 40,
              duration: 500,
              maxZoom: 14,
            });
          }
        })
        .catch(() => {
          // bounds fit is best-effort; map already has a sane Portland default
        });

      // Click an alert → navigate to its detail page.
      map.on("click", "alerts-circle", (e) => {
        const feat = e.features?.[0];
        const alertId = feat?.properties?.alert_id;
        if (alertId) router.push(`/w/${watchlistId}/alert/${alertId}`);
      });
      map.on("mouseenter", "alerts-circle", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "alerts-circle", () => {
        map.getCanvas().style.cursor = "";
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [watchlistId, router]);

  return <div ref={containerRef} className={className} />;
}

function computeBounds(
  fc: GeoJSON.FeatureCollection,
): maplibregl.LngLatBoundsLike | null {
  const b = new maplibregl.LngLatBounds();
  let any = false;
  for (const feat of fc.features) {
    walk(feat.geometry, (lng, lat) => {
      b.extend([lng, lat]);
      any = true;
    });
  }
  return any ? b : null;
}

function walk(geom: GeoJSON.Geometry, cb: (lng: number, lat: number) => void): void {
  if (geom.type === "Point") {
    const [lng, lat] = geom.coordinates as [number, number];
    cb(lng, lat);
  } else if (geom.type === "MultiPoint" || geom.type === "LineString") {
    for (const c of geom.coordinates as [number, number][]) cb(c[0], c[1]);
  } else if (geom.type === "Polygon" || geom.type === "MultiLineString") {
    for (const ring of geom.coordinates as [number, number][][]) {
      for (const c of ring) cb(c[0], c[1]);
    }
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.coordinates as [number, number][][][]) {
      for (const ring of poly) for (const c of ring) cb(c[0], c[1]);
    }
  } else if (geom.type === "GeometryCollection") {
    for (const g of geom.geometries) walk(g, cb);
  }
}
