# Environment Setup

This document walks through the one-time infrastructure setup required before running `purpleteam build` to spin up lab segments. Follow the sections in order.

---

## Overview

The lab environment consists of:

| Component | Type | Purpose |
|---|---|---|
| **pfSense** | VM | Firewall/router. WAN faces the Proxmox host bridge (`vmbr0`); each lab segment gets a dedicated LAN interface added by `purpleteam build`. |
| **SDN Simple Zone** | Proxmox SDN | Logical container for all lab VNets. |
| **Admin VNet** | SDN VNet | Permanent management network. pfSense serves DHCP and NAT here. |
| **Admin host** | LXC container | Debian container on the admin VNet for management tasks. |
| **Templates** | VMs | Kali Linux, Debian Linux, and Windows Workstation — cloned by `purpleteam build` into each lab segment. |

---

## 1. Prerequisites

- A Proxmox VE host with internet access via `vmbr0` (the default Linux bridge).
- ISO images downloaded to Proxmox local storage:
  - [pfSense CE](https://www.pfsense.org/download/) — AMD64, DVD image (ISO).
  - [Kali Linux](https://www.kali.org/get-kali/#kali-installer-images) — 64-bit installer ISO.
  - [Debian](https://www.debian.org/distrib/netinst) — AMD64 netinst ISO.
  - [Windows 11](https://www.microsoft.com/software-download/windows11) — ISO.
  - [VirtIO drivers for Windows](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso) — required for Windows VMs on Proxmox.
- The `purpleteam` CLI installed: `pip install ./environment` (see [environment/](./)).

---

## 2. SDN Simple Zone and Admin VNet

These are created once and persist across all lab builds.

### 2a. Create the Simple Zone

1. In the Proxmox web UI, go to **Datacenter → SDN → Zones → Add → Simple**.
2. Set:
   - **ID**: `labzone` (or your preferred name — use this value for `--zone` when running `purpleteam build`).
3. Click **Add**.

### 2b. Create the Admin VNet

1. Go to **Datacenter → SDN → VNets → Add**.
2. Set:
   - **Name**: `adminnet`
   - **Zone**: `labzone`
3. Click **Add**.
4. Click **Apply** (top-right of the SDN page) to push the configuration to all nodes.

> `purpleteam build` will create additional VNets in `labzone` (e.g. `labnet1`, `labnet2`) — one per lab segment.

---

## 3. pfSense Firewall VM

pfSense acts as the router for every lab segment. `purpleteam build` automatically adds a new NIC to this VM for each segment it creates; you then assign and configure those interfaces inside pfSense.

### 3a. Create the VM

1. **Datacenter → node → Create VM**.
2. Recommended settings:

   | Setting | Value |
   |---|---|
   | Name | `pfsense` |
   | ISO | pfSense CE ISO |
   | OS type | Other |
   | CPU | 2 cores |
   | RAM | 2 GB |
   | Disk | 16 GB, VirtIO SCSI |
   | Network (net0) | Bridge `vmbr0` — this is the **WAN** interface |

3. Add a second NIC before starting the VM:
   - **VM → Hardware → Add → Network Device**
   - Bridge: `adminnet`, Model: `VirtIO`
   - This will become the **LAN (admin) interface**.

4. Start the VM and complete the pfSense installer (accept defaults, install to the VirtIO disk).

### 3b. Initial pfSense Interface Assignment

On first boot, pfSense will prompt to assign interfaces:

1. Decline VLAN setup when asked.
2. Assign interfaces:
   - **WAN** → `vtnet0` (the `vmbr0` NIC — will obtain an IP via DHCP from your network).
   - **LAN** → `vtnet1` (the `adminnet` NIC).
3. Set the LAN IP when prompted, e.g. **`10.0.0.1/24`**.

### 3c. Configure LAN for Internet Access

pfSense enables NAT from LAN to WAN by default, so admin VNet clients will have internet access as soon as DHCP is running. Verify or configure this in the web UI (connect from the admin host once it is set up in section 5):

1. Browse to `https://10.0.0.1` (accept the self-signed certificate).
2. Default credentials: `admin` / `pfsense` — **change these immediately**.
3. Confirm under **Firewall → NAT → Outbound** that **Automatic outbound NAT** is enabled.
4. Confirm under **Services → DHCP Server → LAN** that DHCP is enabled for the `10.0.0.0/24` range.

### 3d. Note the VM ID

Record the pfSense VM ID (visible in the Proxmox sidebar). This is the `--firewall` value for `purpleteam build`.

---

## 4. VM Templates

Templates are created once. `purpleteam build` performs full clones of these templates into each lab segment and reassigns `net0` on every clone to the segment's VNet.

> **Important:** Do not attach a persistent network bridge to any template. `purpleteam build` sets `net0` on each clone to the appropriate lab VNet bridge at creation time. Templates can have `net0` set to any bridge as a placeholder — it will be overwritten on the clone.

> **LXC note:** The `purpleteam build` script operates on QEMU VMs. Create Debian as a VM (not an LXC container) if you want it included in lab segment clones. LXC is fine for the admin host (section 5) since that is not cloned.

---

### 4a. Kali Linux VM

1. **Create VM**: 2 vCPU, 4 GB RAM, 40 GB VirtIO SCSI disk, `net0` on any bridge as placeholder, boot from Kali ISO.
2. Install Kali Linux (graphical or minimal — your preference).
3. Enable SSH: `sudo systemctl enable --now ssh`
4. Shut down the VM.
5. **Convert to template**: Right-click the VM in the Proxmox sidebar → **Convert to Template**.
6. Record the template VMID for use with `--templates`.

---

### 4b. Debian Linux VM

1. **Create VM**: 1 vCPU, 1 GB RAM, 16 GB VirtIO SCSI disk, `net0` on any bridge as placeholder, boot from Debian netinst ISO.
2. Install Debian (minimal, no desktop required).
3. Install SSH server during setup, or afterwards: `sudo apt install -y openssh-server`
4. Shut down the VM.
5. **Convert to template**: Right-click → **Convert to Template**.
6. Record the template VMID.

---

### 4c. Windows Workstation VM

The `vm-prep/windows/` scripts prepare Windows for Ansible management and sysprep the image for cloning.

#### Install Windows

1. **Create VM**:

   | Setting | Value |
   |---|---|
   | Name | `win11-template` |
   | ISO | Windows 11 ISO |
   | OS type | Microsoft Windows 11 |
   | CPU | 2 cores |
   | RAM | 4 GB |
   | Disk | 64 GB, VirtIO SCSI |
   | Network (net0) | Any bridge as placeholder |

2. Add the VirtIO drivers ISO as a second CD-ROM drive (required so Windows can see the VirtIO disk and NIC during install).
3. Start the VM. During Windows Setup, when the disk is not detected, click **Load driver** and browse the VirtIO CD for `viostor\w11\amd64`.
4. Complete the Windows 11 installation. Create any local account to get through OOBE — it will be replaced by sysprep.

#### Run vm-prep Scripts

Copy the contents of `vm-prep/windows/` to the VM (e.g. via RDP or a shared drive), then run inside the VM:

**Step 1 — Pre-sysprep** (run as Administrator in PowerShell):
```powershell
.\pre-sysprep.ps1
```
This script:
- Enables and configures **WinRM** for Ansible (HTTP listener, basic auth, increased envelope size).
- Enables **PowerShell Remoting**.
- Opens **firewall rules** for WinRM ports 5985 and 5986.
- Sets the **execution policy** to `RemoteSigned`.
- Installs **OpenSSH Server** (optional SSH transport for Ansible).
- Cleans temp files, logs, and Windows Update cache to keep the template image lean.

**Step 2 — Generalize** (run as Administrator in a Command Prompt, in the same folder as `unattend.xml`):
```cmd
generalize.cmd
```
This runs `sysprep /generalize /oobe /shutdown` with the provided `unattend.xml`. The VM **shuts down automatically** when complete.

The `unattend.xml` configures each clone on first boot:
- Restarts WinRM and OpenSSH so Ansible can connect immediately.
- Skips all OOBE screens.
- Creates a local administrator account:
  - **Username**: `ansible`
  - **Password**: `AnsibleBootstrap1!`
  - ⚠️ Change or rotate this password via Ansible after first contact.
- Sets the computer name randomly (unique per clone) and timezone to UTC.

#### Convert to Template

Once the VM is shut down (sysprep complete), right-click it in Proxmox → **Convert to Template**. Record the VMID.

---

## 5. Admin Host (Debian LXC)

The admin host provides a persistent management workstation on `adminnet` for accessing pfSense, running Ansible, and monitoring the lab.

1. **Datacenter → node → Create CT** (LXC container).
2. Download a Debian container template if not already available: **node → local storage → CT Templates → Templates → search "debian"**.
3. Recommended settings:

   | Setting | Value |
   |---|---|
   | Hostname | `admin` |
   | Template | Debian (latest) |
   | CPU | 1 core |
   | RAM | 512 MB |
   | Disk | 8 GB |
   | Network (eth0) | Bridge `adminnet`, DHCP (or static e.g. `10.0.0.10/24`, gateway `10.0.0.1`) |

4. Start the container and verify internet connectivity: `ping 1.1.1.1`
5. Install useful tools: `apt install -y ansible python3 curl git`

---

## 6. Building Lab Segments

With infrastructure in place, use the `purpleteam` CLI to spin up isolated lab segments.

### One-time configuration

```bash
purpleteam-setup
```
Enter the Proxmox host, API user, token name/value, and default node. These are saved to `~/.config/purpleteam/config.json` and used as defaults for every subsequent run.

### Create lab segments

```bash
purpleteam build \
  --count 3 \
  --templates 101,102,103 \
  --zone labzone \
  --vnet-prefix labnet \
  --firewall 100
```

Replace the values with your actual template VMIDs and pfSense VMID. This will:

1. Create VNets `labnet1`, `labnet2`, `labnet3` in `labzone`.
2. Apply SDN configuration once.
3. For each VNet: clone all specified templates, set `net0` on each clone to the VNet bridge.
4. Add a new NIC on the pfSense VM for each VNet (appears as `vtnetN` inside pfSense).

### Post-build: configure new pfSense interfaces

After running `purpleteam build`, log into the pfSense web UI and for each new interface:

1. **Interfaces → Assignments** — assign the new `vtnetN` to an interface (e.g. `OPT1`, `OPT2`).
2. Enable the interface and set a static IP (e.g. `10.X.0.1/24`).
3. **Services → DHCP Server** — enable DHCP on the new interface.
4. **Firewall → Rules** — add a rule allowing LAN → WAN traffic if not inherited.

Internet access for the segment's VMs will then route through pfSense's NAT to `vmbr0`.
