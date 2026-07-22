# HikCentral Attendance Integration

This module integrates the HikCentral biometric attendance system with Odoo's attendance management by providing a direct database connection interface.

## Features

- Direct database integration with HikCentral access control system
- Creates a dedicated database table for HikCentral to write attendance data
- Automatically processes biometric attendance records to Odoo HR attendance
- Support for temperature scanning and mask detection data
- Real-time data synchronization through scheduled jobs
- Support for both direct database integration and Excel import

## Installation

### Prerequisites
- Odoo 18.0

### Steps
1. Install the module in your Odoo instance
2. Configure the HikCentral web portal to send data to your Odoo database
3. Set up the mapping between HikCentral employee IDs and Odoo employees

## Configuration in HikCentral

### Database Connection Setup
1. In the HikCentral web portal, navigate to System > Third-Party Integration > Data Interchange
2. Set up database connection with the following details:
   - Host: Your Odoo database host
   - Port: Your database port (typically 5432 for PostgreSQL)
   - Database: Your Odoo database name
   - Username: Database user with write permissions
   - Password: Database user password
3. In the table mapping, use `hik_access_data_interchange` as the target table
4. Map the HikCentral fields to the corresponding columns in the Odoo table

## Usage

### Viewing HikCentral Records
1. Go to Attendances > HikCentral Data Interchange
2. Use filters to find specific records
3. Review the automatic synchronization status

### Manual Processing
1. Select unprocessed records
2. Click "Process to Attendance"

### Schedule Automatic Processing
1. Go to Settings > Technical > Scheduled Actions
2. The "Process HikCentral Data Interchange" job runs every 5 minutes by default
3. Adjust the frequency if needed

## Field Mapping Reference

When configuring HikCentral, use these field names in the Odoo table:

| HikCentral Field | Odoo Field Name |
|------------------|-----------------|
| Employee ID      | employeeid      |
| First Name       | firstname       |
| Last Name        | lastname        |
| Person Name      | personname      |
| Card Number      | cardno          |
| DateTime         | authdatetime    |
| Device Name      | devicename      |
| Device Serial    | devicesn        |
| Direction        | direction       |
| Auth Result      | authresult      |
| Temperature      | temperature     |
| Mask Status      | maskstatus      |

## Compatibility
This module is compatible with Odoo 18.0 and HikCentral Access Control systems.
