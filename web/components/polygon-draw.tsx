"use client";

import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import "maplibre-gl/dist/maplibre-gl.css";

import MapboxDraw from "@mapbox/mapbox-gl-draw";
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";

const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const PORTLAND_CENTER: [number, number] = [-122.66, 45.535];
const PORTLAND_ZOOM = 11;
const MAX_VERTICES = 50;

export function PolygonDraw({
  onChange,
  className,
}: {
  onChange: (polygon: GeoJSON.Polygon | null) => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

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

    // mapbox-gl-draw checks for a global maplibre/mapbox; stub if absent.
    const w = window as unknown as { mapboxgl?: unknown };
    if (!w.mapboxgl) w.mapboxgl = maplibregl;

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      defaultMode: "draw_polygon",
    });
    drawRef.current = draw;
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    const emit = () => {
      const fc = draw.getAll();
      const feat = fc.features.find((f) => f.geometry.type === "Polygon") as
        | GeoJSON.Feature<GeoJSON.Polygon>
        | undefined;
      if (!feat) {
        onChangeRef.current(null);
        return;
      }
      const ring = feat.geometry.coordinates[0];
      // Cap vertices: if user drew >50, just take the first 50 + close.
      if (ring.length - 1 > MAX_VERTICES) {
        const trimmed = [...ring.slice(0, MAX_VERTICES), ring[0]];
        feat.geometry.coordinates[0] = trimmed;
      }
      // Single polygon only — wipe any extras.
      const others = fc.features.filter((f) => f.id !== feat.id);
      others.forEach((o) => draw.delete(o.id as string));
      onChangeRef.current(feat.geometry);
    };

    map.on("draw.create", emit);
    map.on("draw.update", emit);
    map.on("draw.delete", () => onChangeRef.current(null));

    return () => {
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className={className} />;
}
