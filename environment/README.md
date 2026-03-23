# Environment Setup

This document walks through the one-time infrastructure setup required before running `purpleteam build` to spin up lab segments. Follow the sections in order.

---

## Overview

| Component | Type | Purpose |
|---|---|---|
| **pfSense** | VM | Firewall/router. WAN faces the Proxmox host bridge (`vmbr0`); each lab segment gets a dedicated LAN interface added by `purpleteam build`. |
| **SDN Simple Zone** | Proxmox SDN | Logical container for all lab VNets. |
| **Admin VNet** | SDN VNet | Permanent management network. pfSense serves DHCP and NAT here. |
| **Admin host** | LXC container | Debian container on the admin VNet for management tasks. |
| **Templates** | VMs | Kali Linux, Debian Linux, and Windows — cloned by `purpleteam build` into each lab segment. |

---

## Prerequisites

- A Proxmox VE host with internet access via `vmbr0`.
- ISO images downloaded to Proxmox local storage:
  - [pfSense CE](https://www.pfsense.org/download/) — AMD64, DVD image.
  - [Kali Linux](https://www.kali.org/get-kali/#kali-installer-images) — 64-bit installer ISO.
  - [Debian](https://www.debian.org/distrib/netinst) — AMD64 netinst ISO.
  - [Windows 11](https://www.microsoft.com/software-download/windows11) — ISO.
  - [VirtIO drivers for Windows](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso) — required for Windows VMs on Proxmox.
- The `purpleteam` CLI installed: `pip install ./environment`

---

## 1. SDN Zone and Admin VNet (automated)

Run `purpleteam-init` to create the SDN simple zone, admin VNet, and admin Debian LXC container in one step:

```bash
purpleteam-init
```

You will be prompted for the zone ID (e.g. `labzone`), admin VNet name (default: `adminnet`), admin container hostname (default: `admin`), and the Proxmox storage ID to use for the container template. The script will:

1. Create the SDN simple zone.
2. Create the admin VNet inside it.
3. Apply the SDN configuration.
4. Download the latest Debian standard LXC template if not already present.
5. Create and start a Debian LXC container on the admin VNet.

If you prefer to do this manually, see the sections below.

### Manual: Create the SDN Simple Zone

1. **Datacenter → SDN → Zones → Add → Simple**
2. Set **ID** to your zone name (e.g. `labzone`). This is the value for `--zone` when running `purpleteam build`.
3. Click **Add**.

### Manual: Create the Admin VNet

1. **Datacenter → SDN → VNets → Add**
2. Set **Name** to `adminnet` and **Zone** to your zone.
3. Click **Add**, then **Apply**.

---

## 2. pfSense Firewall VM

pfSense acts as the router for every lab segment. `purpleteam build` automatically adds a new NIC to this VM for each segment; you then assign and configure those interfaces inside pfSense.

### Create the VM

1. **Datacenter → node → Create VM**
2. Use the pfSense CE ISO. Set the OS type to **Other**.
3. Add two network interfaces:
   - **net0**: Bridge `vmbr0` — this becomes the **WAN** interface.
   - **net1**: Bridge `adminnet` — this becomes the **LAN (admin)** interface.
4. Start the VM and complete the pfSense installer (accept defaults, install to disk).

### Initial Interface Assignment

On first boot, pfSense prompts to assign interfaces:

1. Decline VLAN setup when asked.
2. Assign:
   - **WAN** → `vtnet0` (gets an IP via DHCP from `vmbr0`).
   - **LAN** → `vtnet1`.
3. Set the LAN IP when prompted, e.g. `10.0.0.1/24`.

### Configure LAN for Internet Access

pfSense enables outbound NAT from LAN to WAN automatically. Verify this in the web UI once the admin host is running (section 3):

1. Browse to `https://10.0.0.1`. Default credentials are `admin` / `pfsense` — **change these immediately**.
2. Confirm **Firewall → NAT → Outbound** is set to **Automatic outbound NAT**.
3. Confirm **Services → DHCP Server → LAN** has DHCP enabled for your subnet.

### Note the VM ID

Record the pfSense VMID from the Proxmox sidebar. This is the `--firewall` value for `purpleteam build`.

---

## 3. Admin Host (Debian LXC)

If you ran `purpleteam-init`, the admin container was already created. Otherwise, create a Debian LXC container manually and attach it to `adminnet` with DHCP (or a static IP in your LAN subnet, e.g. `10.0.0.10/24` with gateway `10.0.0.1`).

Once running:

```bash
# Verify internet access
ping 1.1.1.1

# Install tools
apt install -y ansible python3 curl git
```

---

## 4. VM Templates

Templates are created once. `purpleteam build` performs full clones into each lab segment and reassigns `net0` on every clone to the segment's VNet.

> **Note:** Do not assign a persistent network bridge to templates. `purpleteam build` overwrites `net0` on every clone with the appropriate lab VNet bridge at creation time.

> **LXC note:** `purpleteam build` operates on QEMU VMs only. If you want Debian included in cloned lab segments, create it as a VM rather than an LXC container. LXC is fine for the admin host (section 3) since it is not cloned.

---

### Kali Linux VM

1. Create a VM and boot from the Kali Linux ISO.
2. Complete the installation.
3. Enable SSH: `sudo systemctl enable --now ssh`
4. Shut down the VM.
5. Right-click in the Proxmox sidebar → **Convert to Template**. Record the VMID.

---

### Debian Linux VM

1. Create a VM and boot from the Debian netinst ISO.
2. Complete a minimal install. Enable the SSH server during setup.
3. Shut down the VM.
4. Right-click → **Convert to Template**. Record the VMID.

---

### Windows Workstation VM

#### Install Windows

1. Create a VM and boot from the Windows 11 ISO. Add the VirtIO drivers ISO as a second CD-ROM drive.
2. During Windows Setup, when the disk is not detected, click **Load driver** and point it to `viostor\w11\amd64` on the VirtIO CD.
3. Complete the Windows 11 installation.

#### Run the vm-prep Scripts

Copy the contents of `vm-prep/windows/` into the VM, then run the following **as Administrator**:

**Step 1 — Pre-sysprep** (PowerShell):
```powershell
.\pre-sysprep.ps1
```

This configures WinRM (HTTP listener, basic auth) and PowerShell Remoting for Ansible, opens firewall rules for WinRM ports 5985/5986, installs OpenSSH Server, sets the execution policy to `RemoteSigned`, and cleans temp files and logs.

**Step 2 — Generalize** (Command Prompt, from the same folder as `unattend.xml`):
```cmd
generalize.cmd
```

This runs `sysprep /generalize /oobe /shutdown`. The VM **shuts down automatically** when complete.

The `unattend.xml` applied to each clone on first boot will:
- Re-enable WinRM and OpenSSH.
- Skip all OOBE screens and set timezone to UTC.
- Create a local administrator account:
  - **Username**: `admin`
  - **Password**: `Password123!`
  - ⚠️ Change this password on first use.

#### Convert to Template

Once the VM has shut down, right-click it → **Convert to Template**. Record the VMID.

---

## 5. Building Lab Segments

### One-time configuration

```bash
purpleteam-setup
```

Saves Proxmox connection defaults (host, user, token, node) to `~/.config/purpleteam/config.json`.

### Create lab segments

```bash
purpleteam build \
  --count 3 \
  --templates 101,102,103 \
  --zone labzone \
  --vnet-prefix labnet \
  --firewall 100
```

Replace values with your actual template VMIDs and pfSense VMID. This will:

1. Create VNets `labnet1`, `labnet2`, `labnet3` in `labzone`.
2. Apply SDN configuration once.
3. For each VNet: clone all specified templates and set `net0` on each clone to the VNet bridge.
4. Add a new NIC to the pfSense VM for each VNet.

Any omitted flags will be prompted interactively.

### Post-build: configure new pfSense interfaces

After `purpleteam build` runs, log into the pfSense web UI and for each new `vtnetN` interface:

1. **Interfaces → Assignments** — assign the new interface (e.g. `OPT1`, `OPT2`).
2. Enable the interface and set a static IP (e.g. `10.X.0.1/24`).
3. **Services → DHCP Server** — enable DHCP on the interface.
4. **Firewall → Rules** — add a rule allowing traffic from the interface to WAN.

VMs in each segment will then route through pfSense to `vmbr0` for internet access.
