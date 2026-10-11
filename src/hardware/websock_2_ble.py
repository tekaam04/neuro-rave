import asyncio
import json
import time

from bleak import BleakScanner, BleakClient
import websockets

SERVICE_UUID = "19B10010-E8F2-537E-4F6C-D104768A1214".lower()
CHAR_UUID = "19B10011-E8F2-537E-4F6C-D104768A1214"

WS_URL = "ws://127.0.0.1:8733/ws"

THRESHOLD = 0.6
DURATION = 2.0#30.0


async def main():
    # --- Find BLE device ---
    print("Scanning for device...")
    devices = await BleakScanner.discover(timeout=10.0)

    device = None
    for d in devices:
        print("seen:", d.name, d.address)

        if d.name and ("Arduino" in d.name or "NeuroHaptic" in d.name):
            device = d
            break

    if device is None:
        print("Device not found.")
        return

    print("Found:", device.name)

    # --- Connect BLE ---
    async with BleakClient(device) as client:
        print("BLE connected")

        #     # --- TEST BUZZ (no WebSocket yet) ---
        # print("Sending test buzz...")
        # await client.write_gatt_char(CHAR_UUID, bytearray([0x01]))
        # await asyncio.sleep(5)

        # return  # stop here for now

        # --- Connect to EEG feature stream ---
        async with websockets.connect(WS_URL) as ws:
            print("Connected to feature stream")

            # low_start = None
            # buzzed = False
            last_buzz = None

            while True:
                msg = json.loads(await ws.recv())

                if msg["type"] != "features":
                    continue

                focus = msg["focus"]
                now = time.monotonic()

                print("focus:", round(focus, 3))

                # if focus < THRESHOLD:
                #     if low_start is None:
                #         low_start = now
                #     print("low for:", round(now - low_start, 1))


                #     if (now - low_start) > DURATION and not buzzed:
                #         print("LOW ATTENTION → BUZZ")
                #         await client.write_gatt_char(CHAR_UUID, bytearray([0x01]))
                #         buzzed = True
                # else:
                #     # reset when attention comes back
                #     low_start = None
                #     buzzed = False

                if focus < THRESHOLD:
                    if last_buzz is None or (now - last_buzz) >= DURATION:
                        print("LOW ATTENTION → BUZZ")
                        await client.write_gatt_char(CHAR_UUID, bytearray([0x01]), response=True)
                        last_buzz = now
                else:
                    last_buzz = None


if __name__ == "__main__":
    asyncio.run(main())