"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const element = document.getElementById("delivery-map");
  const lat = document.getElementById("id_latitude");
  const lng = document.getElementById("id_longitude");
  const notice = document.getElementById("map-notice");
  const configElement = document.getElementById("map-config");
  if (!element || !lat || !lng || !configElement) return;
  const explain = (text) => {
    if (notice) {
      notice.textContent = text;
      notice.hidden = false;
    }
  };
  if (!window.L) {
    explain(
      "Peta belum dapat dimuat. Koordinat dan alamat tetap bisa diisi manual.",
    );
    return;
  }
  try {
    const config = JSON.parse(configElement.textContent);
    const currentLat = Number(lat.value),
      currentLng = Number(lng.value);
    const hasPin =
      lat.value !== "" &&
      lng.value !== "" &&
      Number.isFinite(currentLat) &&
      Number.isFinite(currentLng) &&
      Math.abs(currentLat) <= 90 &&
      Math.abs(currentLng) <= 180;
    const readonly = lat.disabled || lng.disabled;
    const map = L.map(element, { scrollWheelZoom: false }).setView(
      hasPin ? [currentLat, currentLng] : [-2.5489, 118.0149],
      hasPin ? 16 : 4,
    );
    const attribution = document.createElement("span");
    attribution.textContent = config.attribution;
    const layer = L.tileLayer(config.tileUrl, {
      maxZoom: 19,
      attribution: config.attribution.includes("OpenStreetMap contributors")
        ? attribution.innerHTML.replace(
            "OpenStreetMap contributors",
            '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>',
          )
        : attribution.innerHTML,
      updateWhenIdle: true,
      keepBuffer: 1,
    }).addTo(map);

    layer.on("tileerror", () =>
      explain(
        "Sebagian gambar peta belum tersedia. Coba lagi; koordinat dan alamat tetap bisa diisi manual.",
      ),
    );
    let marker = hasPin
      ? L.marker([currentLat, currentLng], { draggable: !readonly }).addTo(map)
      : null;
    const selected = (point) => {
      if (readonly) return;
      lat.value = point.lat.toFixed(6);
      lng.value = point.lng.toFixed(6);
      if (!marker) {
        marker = L.marker(point, { draggable: !readonly }).addTo(map);
        marker.on("dragend", () => selected(marker.getLatLng()));
      } else marker.setLatLng(point);
      const confirm = document.getElementById("id_pin_confirmed");
      if (confirm) confirm.checked = false;
      explain(
        "Titik diperbarui. Periksa alamat lengkap dan konfirmasikan kembali titiknya.",
      );
    };
    if (marker) marker.on("dragend", () => selected(marker.getLatLng()));
    map.on("click", (event) => selected(event.latlng));
    document.getElementById("use-location")?.addEventListener("click", () => {
      if (!navigator.geolocation) {
        explain("Lokasi perangkat tidak tersedia. Pilih titik secara manual.");
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const point = {
            lat: position.coords.latitude,
            lng: position.coords.longitude,
          };
          selected(point);
          map.setView(point, 16);
        },
        () =>
          explain(
            "Izin lokasi tidak diberikan atau lokasi belum ditemukan. Pilih titik secara manual.",
          ),
        { timeout: 10000, maximumAge: 60000 },
      );
    });
    element.closest("details")?.addEventListener("toggle", () => {
      if (element.closest("details").open)
        setTimeout(() => map.invalidateSize(), 100);
    });
    [lat, lng].forEach((input) =>
      input.addEventListener("change", () => {
        const point = { lat: Number(lat.value), lng: Number(lng.value) };
        if (
          lat.value !== "" &&
          lng.value !== "" &&
          Number.isFinite(point.lat) &&
          Number.isFinite(point.lng) &&
          Math.abs(point.lat) <= 90 &&
          Math.abs(point.lng) <= 180
        ) {
          selected(point);
          map.setView(point, 16);
        }
      }),
    );
  } catch (_) {
    explain(
      "Peta belum dapat disiapkan. Gunakan koordinat manual dan periksa alamat.",
    );
  }
});
