# IoT Data Logging & CSV Export System — Project Plan

## 1. Project Objective

Build a lightweight IoT data logging system for up to 10 devices.

The system will:

- Receive device data over MQTT
- Validate incoming parameters against an admin-managed whitelist
- Store only approved data in PostgreSQL
- Allow an admin to manage devices and allowed parameters
- Allow stored data to be exported to CSV using a start date/time and end date/time
- Run locally during development on a Proxmox VM
- Be deployed to the client VPS using Docker

The system is intentionally simple and does not include unnecessary enterprise features.

---

## 2. System Architecture

**Data flow:**

Device → MQTT Broker → Backend → PostgreSQL → CSV Export

### Core Components

1. **Mosquitto**
   - Receives MQTT messages from devices

2. **Python / FastAPI Backend**
   - Processes incoming MQTT messages
   - Checks the parameter whitelist
   - Stores approved data
   - Provides the admin interface
   - Handles CSV export

3. **PostgreSQL**
   - Stores devices
   - Stores approved parameter definitions
   - Stores telemetry data
   - Stores admin/user information

4. **Simple Admin Panel**
   - Admin login
   - Device management
   - Parameter whitelist management
   - Data viewing
   - CSV export

5. **Caddy or Nginx**
   - Reverse proxy
   - HTTPS access in production

6. **Docker / Docker Compose**
   - Runs and manages the complete application stack

---

## 3. Development Environment

Development will be performed on a Proxmox VM.

### Development VM

Recommended:

- Ubuntu Server 24.04 LTS
- 2–4 vCPU
- 4–8 GB RAM
- 40–60 GB storage

### Software Required

Install in this order:

1. Ubuntu Server 24.04 LTS
2. Git
3. Docker Engine
4. Docker Compose
5. Project repository
6. Application containers

---

## 4. Production Environment

The completed system will be deployed to the client VPS.

Recommended VPS:

- 2 vCPU
- 8 GB RAM
- 80–100 GB SSD/NVMe
- Ubuntu Server 24.04 LTS

Production will use the same Docker-based structure tested on the Proxmox VM.

Only environment-specific configuration will change, such as:

- Domain name
- Database password
- MQTT credentials
- Admin credentials
- HTTPS configuration
- Backup location

---

## 5. Functional Scope

### 5.1 Admin Login

A simple authenticated admin area will be provided.

The admin will be able to access:

- Devices
- Allowed parameters
- Stored data
- CSV export

Only basic admin access is required for the initial system.

---

### 5.2 Device Management

The admin can:

- Register a device
- Set a device name
- Set a unique device ID
- Enable or disable a device
- View registered devices

The system is designed for a maximum of approximately 10 devices.

---

### 5.3 Parameter Whitelist

The admin can define which incoming parameters are allowed to be stored.

The admin can:

- Add an allowed parameter
- Remove a parameter
- Enable or disable a parameter
- View the current whitelist

When an MQTT message arrives:

- Approved parameters are accepted
- Unapproved parameters are ignored
- Unapproved parameters are not stored in the database

---

## 6. MQTT Data Ingestion

Devices will publish telemetry to the Mosquitto MQTT broker.

The backend will subscribe to the required MQTT topic or topics.

For each incoming message, the backend will:

1. Identify the sending device
2. Validate the message
3. Check whether the device is registered and enabled
4. Compare received parameters with the admin whitelist
5. Ignore parameters that are not approved
6. Store approved parameters in PostgreSQL
7. Store the message timestamp

The implementation should remain tolerant of invalid or incomplete messages without crashing the service.

---

## 7. Database Plan

Only one PostgreSQL database is required.

### Main Data Areas

#### Devices

Stores basic registered-device information.

Typical information:

- Device ID
- Device name
- Enabled/disabled status
- Creation date

#### Allowed Parameters

Stores the whitelist configured by the admin.

Typical information:

- Parameter name
- Enabled/disabled status

#### Telemetry

Stores approved incoming sensor values.

Typical information:

- Timestamp
- Device ID
- Parameter
- Value

#### Admin/User

Stores login information required for the admin panel.

No separate raw/manipulated databases are required.

---

## 8. Stored Data View

The admin panel will include a basic view of stored telemetry.

This is intended for verification and simple inspection, not advanced analytics.

Basic information may include:

- Timestamp
- Device
- Parameter
- Value

---

## 9. CSV Export

The admin can export stored telemetry to a CSV file.

### Export Inputs

Only:

- Start date/time
- End date/time

### Export Process

1. Admin selects the start date/time
2. Admin selects the end date/time
3. Backend queries matching stored data
4. System generates a CSV file
5. User downloads the CSV

The CSV will contain the stored telemetry records within the selected period.

No advanced export filtering is required for the initial scope.

---

## 10. Admin Panel Pages

The initial admin panel should remain minimal.

Suggested pages:

1. **Login**
2. **Devices**
3. **Allowed Parameters**
4. **Stored Data**
5. **CSV Export**
6. **Logout**

No complex custom dashboard is required.

---

## 11. Docker Structure

The production stack should contain only the required services.

### Containers

- Mosquitto
- PostgreSQL
- Backend/Admin Application
- Caddy or Nginx

The backend and admin interface may be packaged together as one application.

Persistent storage must be used for:

- PostgreSQL data
- MQTT configuration where required
- Application configuration
- Backup files where applicable

---

## 12. Development Workflow

### Phase 1 — Project Setup

- Create Proxmox VM
- Install Ubuntu Server
- Install Docker
- Install Git
- Create project repository
- Create Docker Compose structure

### Phase 2 — Database

- Set up PostgreSQL
- Define device storage
- Define parameter whitelist storage
- Define telemetry storage
- Define admin login storage

### Phase 3 — MQTT

- Configure Mosquitto
- Configure MQTT authentication
- Connect backend MQTT subscriber
- Test messages from simulated devices

### Phase 4 — Data Filtering

- Validate device ID
- Validate incoming payload
- Check parameter whitelist
- Ignore unapproved parameters
- Store approved data

### Phase 5 — Admin Panel

- Admin login
- Device registration
- Device enable/disable
- Allowed parameter management
- Basic stored-data view

### Phase 6 — CSV Export

- Date/time selection
- Database query
- CSV file generation
- CSV download

### Phase 7 — Local Testing

- Test multiple devices
- Test approved parameters
- Test unapproved parameters
- Test malformed payloads
- Test database storage
- Test CSV export
- Test container restart and data persistence

### Phase 8 — Production Deployment

- Prepare production environment variables
- Build/tag application image
- Deploy Docker Compose stack to client VPS
- Configure domain
- Configure HTTPS
- Configure MQTT credentials
- Configure backups
- Perform final production testing

---

## 13. Testing Checklist

Before deployment, verify:

- Admin can log in
- Admin can add devices
- Admin can disable devices
- Admin can add allowed parameters
- Admin can remove/disable allowed parameters
- Registered devices can send MQTT data
- Approved parameters are stored
- Unapproved parameters are ignored
- Invalid MQTT payloads do not crash the application
- Telemetry timestamps are stored correctly
- Stored records can be viewed
- CSV export works for selected date/time ranges
- Empty date ranges are handled correctly
- PostgreSQL data survives container restarts
- Services restart correctly after VM/VPS reboot
- HTTPS works in production
- MQTT authentication works
- Database is not publicly exposed

---

## 14. Security Basics

The initial system should include:

- Admin authentication
- MQTT username/password authentication
- HTTPS for the admin panel
- Strong database password
- PostgreSQL accessible only from the application network
- Firewall configuration
- Production secrets stored outside Docker images
- Regular software updates

---

## 15. Backup Plan

At minimum:

- Regular PostgreSQL backup
- Backup of important application configuration
- Backup of MQTT configuration
- Backup stored outside the active PostgreSQL data directory

The client VPS provider's backup feature may also be used as an additional recovery method.

---

## 16. Deliverables

The completed project should include:

- MQTT data ingestion system
- PostgreSQL database
- Admin login
- Device management
- Parameter whitelist management
- Approved-parameter data storage
- Basic stored-data viewer
- Date/time-based CSV export
- Docker configuration
- Production deployment on client VPS
- Basic configuration/documentation
- Source code/project repository

---

## 17. Explicitly Out of Scope

The following are not part of the initial project:

- Load balancing
- Kubernetes
- Redis
- RabbitMQ
- Kafka
- TimescaleDB
- Grafana
- Advanced analytics
- Machine learning
- AI data preparation
- Alerts or notifications
- SMS integration
- Complex user roles/RBAC
- Separate raw and processed databases
- Calibration engine
- Data manipulation engine
- GPS/maps
- Device health monitoring
- Battery monitoring
- Firmware updates
- Custom report builder
- Mobile application
- Advanced CSV filtering
- Multiple export formats

Any of these can be considered as separate future upgrades.

---

## 18. Acceptance Criteria

The project can be considered complete when:

1. Up to 10 registered devices can send MQTT telemetry
2. The server accepts data from registered devices
3. Only admin-approved parameters are stored
4. Unapproved parameters are ignored
5. Data is stored persistently in PostgreSQL
6. Admin can manage devices and allowed parameters
7. Admin can view basic stored telemetry
8. Admin can select a start and end date/time
9. System exports matching telemetry records as CSV
10. System is deployed successfully on the client VPS using Docker
11. Production data survives application/container restarts

---

## 19. Final System Summary

The final system is intentionally lightweight:

**Device → MQTT → Backend → PostgreSQL → CSV Export**

The project focuses only on reliable data collection, parameter filtering, storage, and CSV export for a maximum of approximately 10 devices.

This keeps the system simple, low-resource, easy to maintain, and suitable for the client's current requirements.
