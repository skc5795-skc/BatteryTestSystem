## A-Warrior / JBD BMS Protocol (V4)

The Battery Test System communicates with the BMS over RS485/RS232/UART using the standard A-Warrior/JBD General Protocol V4. The communication follows a strict master-slave request-response architecture where the desktop application acts as the master.

### 1. Frame Structure
All data sent to and from the BMS is encapsulated in a specific frame format.

**Request Frame (Master → BMS)**

| Byte | Description | Hex Value | Notes |
| :--- | :--- | :--- | :--- |
| `0` | **Start Byte** | `0xDD` | Indicates start of frame |
| `1` | **Status** | `0xA5` | Read command (`0x5A` for Write) |
| `2` | **Command Code** | *Variable* | e.g., `0x03` for Basic Info, `0x04` for Cell Voltages |
| `3` | **Data Length** | *Variable* | Length of the data payload (`0x00` if no data) |
| `4...N` | **Data** | *Variable* | Optional payload data |
| `N+1` | **Checksum High** | *Variable* | See Checksum Calculation below |
| `N+2` | **Checksum Low** | *Variable* | See Checksum Calculation below |
| `N+3` | **Stop Byte** | `0x77` | Indicates end of frame |

**Response Frame (BMS → Master)**

| Byte | Description | Hex Value | Notes |
| :--- | :--- | :--- | :--- |
| `0` | **Start Byte** | `0xDD` | Start of frame |
| `1` | **Command Code** | *Variable* | Matches the requested command code |
| `2` | **Status/Error** | `0x00` | `0x00` means success. Non-zero means error. |
| `3` | **Data Length** | *Variable* | Length of the returned payload |
| `4...N` | **Data** | *Variable* | The requested values |
| `N+1` | **Checksum High** | *Variable* | Calculated by BMS |
| `N+2` | **Checksum Low** | *Variable* | Calculated by BMS |
| `N+3` | **Stop Byte** | `0x77` | End of frame |

**Checksum Calculation**
The checksum is a 16-bit integer calculated by adding the Command Code, Data Length, and all Data bytes, then applying a bitwise NOT (`~`) and adding `1`. 

*Formula:* `checksum = (~sum(command + length + data) + 1) & 0xFFFF`

---

### 2. Supported Commands & Data Mapping

#### `CMD 0x03`: Read Basic Battery Information
This command fetches the overall status of the battery pack, including state of charge, capacities, current, and protection flags.
* **Expected Data Length:** $\ge$ 23 bytes

| Byte Offset | Data Type | Field Name | Parsing Logic |
| :--- | :--- | :--- | :--- |
| `0:2` | Unsigned Short | **Total Voltage** | Multiplied by 10 to get `mV` |
| `2:4` | Signed Short | **Current** | Multiplied by 10 to get `mA` *(Negative = Discharging)* |
| `4:6` | Unsigned Short | **Residual Capacity** | Multiplied by 10 to get `mAh` |
| `6:8` | Unsigned Short | **Nominal Capacity** | Multiplied by 10 to get `mAh` |
| `8:10` | Unsigned Short | **Cycle Life** | Raw integer representing total BMS cycles |
| `16:18` | Unsigned Short | **Protection Status** | Bitmask of active BMS protections (See Bitmask below) |
| `18` | Byte | **Software Version** | Raw integer |
| `19` | Byte | **RSOC** | Relative State of Charge (`%`) |
| `20` | Byte | **FET Status** | Indicates if Charge/Discharge MOSFETs are open/closed |
| `21` | Byte | **Cell Count** | Total number of cells configured in BMS |
| `22` | Byte | **NTC Count** | Number of temperature sensors present |
| `23...N` | Unsigned Shorts | **Temperatures** | Reads `NTC Count` pairs of bytes. Formula: `(raw * 0.1) - 273.15` to get °C |

**Protection Status Bitmask (Bytes 16:18)**
This 16-bit integer determines if the BMS has halted operation due to safety limits. In this software, we specifically monitor:
* **Bit 1 (`0x02`): Cell Undervoltage Protection.** If this bit is `1`, the battery has reached its hardware discharge floor, and the software automatically auto-stops the discharge test.

#### `CMD 0x04`: Read Cell Voltages
This command requests the individual voltages for every cell connected to the BMS.
* **Expected Data Length:** 2 bytes per cell (e.g., 28 bytes for a 14S battery).

| Byte Offset | Data Type | Field Name | Parsing Logic |
| :--- | :--- | :--- | :--- |
| `0:2` | Unsigned Short | **Cell 1 Voltage** | Raw value is in `mV`. Divided by `1000.0` to yield Volts. |
| `2:4` | Unsigned Short | **Cell 2 Voltage** | `mV / 1000.0` |
| `...` | ... | ... | ... |
| `N-2:N` | Unsigned Short | **Cell N Voltage** | `mV / 1000.0` |

*Note: The parser reads all voltage pairs until the end of the data payload. If a cell returns < 1.0V or < 2.0V, the UI flags it as "DEAD" or "CRIT" respectively, but it is still parsed and tracked in the overall data array.*
