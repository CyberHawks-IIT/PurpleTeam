"""
Proxmox API operations for the lab segment builder.
All functions accept a ProxmoxAPI instance as their first argument.
"""
import time

from proxmoxer import ProxmoxAPI


def connect(host: str, user: str, token_name: str, token_value: str) -> ProxmoxAPI:
    """Return an authenticated ProxmoxAPI session using an API token."""
    return ProxmoxAPI(
        host,
        user=user,
        token_name=token_name,
        token_value=token_value,
        verify_ssl=False,
    )


def resolve_node(proxmox: ProxmoxAPI, vmid: int) -> str:
    """Return the node name that hosts the given VMID."""
    resources = proxmox.cluster.resources.get(type="vm")
    for r in resources:
        if r.get("vmid") == vmid:
            return r["node"]
    raise ValueError(f"VMID {vmid} not found in cluster")


def resolve_vm_name(proxmox: ProxmoxAPI, node: str, vmid: int) -> str:
    """Return the name of a VM, falling back to 'vm{vmid}' if unset."""
    cfg = proxmox.nodes(node).qemu(vmid).config.get()
    return cfg.get("name", f"vm{vmid}")


def next_vmid(proxmox: ProxmoxAPI) -> int:
    """Return the next available VMID from the cluster."""
    return int(proxmox.cluster.nextid.get())


def create_vnet(proxmox: ProxmoxAPI, zone: str, vnet_name: str) -> None:
    """Create a VNet in the given SDN simple zone."""
    proxmox.cluster.sdn.vnets.post(vnet=vnet_name, zone=zone)


def apply_sdn(proxmox: ProxmoxAPI) -> None:
    """Apply all pending SDN configuration changes."""
    proxmox.cluster.sdn.put()


def clone_vm(
    proxmox: ProxmoxAPI,
    node: str,
    template_vmid: int,
    new_vmid: int,
    new_name: str,
) -> str:
    """
    Full-clone a VM and return the task UPID for polling.
    The clone lands on the same node as the template.
    """
    upid = proxmox.nodes(node).qemu(template_vmid).clone.post(
        newid=new_vmid,
        name=new_name,
        full=1,
    )
    return upid


def wait_for_task(proxmox: ProxmoxAPI, node: str, upid: str, poll_interval: float = 2.0) -> None:
    """Block until a task finishes. Raises RuntimeError if it fails."""
    while True:
        status = proxmox.nodes(node).tasks(upid).status.get()
        if status.get("status") == "stopped":
            exit_status = status.get("exitstatus", "")
            if exit_status != "OK":
                raise RuntimeError(f"Task {upid} failed with exitstatus={exit_status!r}")
            return
        time.sleep(poll_interval)


def set_net0(proxmox: ProxmoxAPI, node: str, vmid: int, bridge: str) -> None:
    """Replace net0 on a VM to use the given bridge (VNet name)."""
    proxmox.nodes(node).qemu(vmid).config.put(net0=f"virtio,bridge={bridge}")


def next_free_net_slot(proxmox: ProxmoxAPI, node: str, vmid: int) -> int:
    """Return the index of the first unused netN slot (0–31) on a VM."""
    cfg = proxmox.nodes(node).qemu(vmid).config.get()
    for i in range(32):
        if f"net{i}" not in cfg:
            return i
    raise RuntimeError(f"VM {vmid} has no free network interface slots (net0–net31 all used)")


def add_net(proxmox: ProxmoxAPI, node: str, vmid: int, slot: int, bridge: str) -> None:
    """Add a network interface at the given slot index to a VM."""
    proxmox.nodes(node).qemu(vmid).config.put(**{f"net{slot}": f"virtio,bridge={bridge}"})
