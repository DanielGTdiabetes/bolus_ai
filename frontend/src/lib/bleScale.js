
const SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
const RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"; // Write
const TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"; // Notify

const CMD_START = "gwc";
const CMD_TARE = "st";

let device = null;
let server = null;
let rxChar = null; // We write to this
let txChar = null; // We receive from this

let onDataCallback = null;

// Stability logic
const STABLE_WINDOW_MS = 1000;
const STABLE_THRESHOLD_G = 3;
let history = [];

export function isBleSupported() {
    return Boolean(navigator.bluetooth);
}

export function setOnData(cb) {
    onDataCallback = cb;
}

export async function connectScale() {
    if (!isBleSupported()) throw new Error("Bluetooth no soportado en este navegador.");

    console.log("Requesting Bluetooth Device...");
    device = await navigator.bluetooth.requestDevice({
        filters: [{ namePrefix: "PROZIS" }, { name: "PROZIS Bit Scale" }],
        optionalServices: [SERVICE_UUID]
    });

    device.addEventListener('gattserverdisconnected', onDisconnected);

    console.log("Connecting to GATT Server...");
    server = await device.gatt.connect();

    console.log("Getting Service...");
    const service = await server.getPrimaryService(SERVICE_UUID);

    console.log("Getting Characteristics...");
    rxChar = await service.getCharacteristic(RX_CHAR_UUID);
    txChar = await service.getCharacteristic(TX_CHAR_UUID);

    console.log("Starting Notifications...");
    await txChar.startNotifications();
    txChar.addEventListener('characteristicvaluechanged', handleNotifications);

    // Start stream automatically
    await startStream();

    return device.name || "Báscula Prozis";
}

export async function disconnectScale() {
    if (device && device.gatt.connected) {
        device.gatt.disconnect();
    }
}

function onDisconnected() {
    console.log('Scale disconnected');
    if (onDataCallback) {
        // Signal disconnection
        onDataCallback({ connected: false });
    }
}

export async function startStream() {
    if (!rxChar) return;
    const encoder = new TextEncoder();
    console.log("Sending START command...");
    try {
        await rxChar.writeValue(encoder.encode(CMD_START));
    } catch (e) {
        console.warn("Retrying start with newline", e);
        await rxChar.writeValue(encoder.encode(CMD_START + "\n"));
    }
}

export async function tare() {
    if (!rxChar) return;
    const encoder = new TextEncoder();
    console.log("Tare...");
    await rxChar.writeValue(encoder.encode(CMD_TARE));
}

function handleNotifications(event) {
    const value = event.target.value;
    // Parse data
    // Expected: [ ... , battery, ... , weightL, weightH ] or similar
    // Payload is binary. 
    // Based on "antomanc/simple-prozis-bit-scale":
    // Battery is at index 1 (0-100)
    // Weight is last 2 bytes (int16 little endian)

    if (value.byteLength < 4) return;

    const batt = value.getUint8(1);
    const grams = value.getInt16(value.byteLength - 2, true);

    // Stability
    const now = Date.now();
    history.push({ t: now, g: grams });
    // Prune old history
    history = history.filter(h => now - h.t <= STABLE_WINDOW_MS);

    let stable = false;
    if (history.length > 5) {
        const vals = history.map(h => h.g);
        const min = Math.min(...vals);
        const max = Math.max(...vals);
        if ((max - min) <= STABLE_THRESHOLD_G) {
            stable = true;
        }
    }

    if (onDataCallback) {
        onDataCallback({
            connected: true,
            grams,
            battery: batt,
            stable,
            raw: value
        });
    }
}
