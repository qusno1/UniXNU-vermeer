// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: minimal source-storage runtime.
//
// sheng's SourceStorage.cpp is a 300 KB ecosystem: the UFS start path plus a boot
// log writer, a UFS benchmark, a process probe, a UI trace probe, a diagnostic
// export, watchdog policy and WiFi/Bluetooth firmware staging. This board needs
// one of those things - the UFS start path - so this file is that path alone.
//
// The sequence is the one sheng uses, in the same order and with the same
// checks, because each step depends on the one before it:
//
//   1. load the original IOStorageFamily, so IOBlockStorageDevice exists;
//   2. confirm its layout matches the source header the adapter was compiled
//      against, because the adapter calls into that base class by offset;
//   3. authenticate the signed root policies against the compiled-in anchor,
//      before any hardware-facing class is registered;
//   4. load the original APFS;
//   5. register the source-built classes (IOBlockStorageDevice subclass, the UFS
//      adapter, the RAM block), which is what makes NativeUfs instantiable;
//   6. create the UFS service on the platform expert and start it.
//
// Everything is fail-loud. A board that reaches this code has already published a
// platform expert, so a missing kext, a changed base-class layout or an
// unauthenticated policy means the storage stack cannot be trusted, and panicking
// with the reason is better than booting a root nobody verified.

#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
#include <IOKit/IOLib.h>

extern kmod_info_t g_kernel_kmod_info;

// The three deferred metaclass constructors, by their compiler-generated names.
extern "C" void source_storage_base_init(void) __asm__("__GLOBAL__sub_I_IOBlockStorageDevice.cpp");
extern "C" void source_storage_ufs_init(void) __asm__("__GLOBAL__sub_I_NativeUfs.cpp");
extern "C" void source_storage_ram_init(void) __asm__("__GLOBAL__sub_I_NativeRamBlock.cpp");

extern "C" IOService *native_ufs_source_create(void);
extern "C" bool native_source_root_policies_load(void);

// NativeUfs records how far its root start got and why it gave up; both are used
// in the panic text so a failed boot names the step instead of a bare message.
extern "C" volatile uint32_t native_ufs_root_step;
extern "C" const char *volatile native_ufs_root_failure;

// NativeUfs polls the board diagnostic during window reads. The minimal runtime
// does not carry one, and the archive's weak reference needs a definition.
extern "C" __attribute__((weak)) void boot_progress_poll(void) {}

namespace {

const OSMetaClass *storageParent;
IOService *storageDriver;
bool attempted;

// The Data seed the loader placed in /chosen/memory-map. sheng starts it after UFS
// because its store window keeps the seed's changed pages. This board has no Data
// seed yet, so the function stays for the day one arrives and does nothing until
// the memory-map actually carries a ramdisk.
void start_data_disk(IOService *provider)
{
	IORegistryEntry *map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
	const bool seed = map && (map->getProperty("PackedRAMDisk") || map->getProperty("RAMDisk"));
	OSSafeReleaseNULL(map);
	if (!seed) {
		return;
	}
	IOService *disk = OSDynamicCast(IOService, OSMetaClass::allocClassWithName("NativeRamBlock"));
	if (!disk) {
		panic("SourceStorage: cannot allocate the Data disk");
	}
	const char *step = !disk->init() ? "init" : !disk->attach(provider) ? "attach"
	    : !disk->start(provider) ? "start" : nullptr;
	if (step) {
		panic("SourceStorage: Data disk %s failed", step);
	}
	printf("SourceStorage: Data disk started\n");
}

}  // namespace

// Used only by the deferred source IOBlockStorageDevice metaclass constructor.
// The C++ class name stays unchanged for compiler-authored arm64e discriminators.
extern "C" const OSMetaClass *native_source_storage_parent(void)
{
	if (!storageParent) {
		panic("SourceStorage: metaclass initialized before original family");
	}
	return storageParent;
}

extern "C" void native_source_storage_start(void)
{
	unsigned enabled = 0;
	if (!PE_parse_boot_argn("native-source-storage", &enabled, sizeof(enabled)) ||
	    enabled != 1 || attempted) {
		return;
	}
	attempted = true;

	OSReturn status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOStorageFamily");
	if (status != kOSReturnSuccess) {
		panic("SourceStorage: IOStorageFamily load failed %x", status);
	}

	const OSSymbol *name = OSSymbol::withCString("IOBlockStorageDevice");
	storageParent = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
	if (name) {
		name->release();
	}
	if (!storageParent || storageParent->getClassSize() != sizeof(IOBlockStorageDevice)) {
		panic("SourceStorage: original base layout %u differs from source %lu",
		    storageParent ? storageParent->getClassSize() : 0,
		    (unsigned long)sizeof(IOBlockStorageDevice));
	}

	// Authenticate the policies before registering anything hardware-facing: the
	// adapter must not be able to publish a root that was never verified.
	if (!native_source_root_policies_load()) {
		panic("SourceStorage: root policy handoff or authentication failed");
	}

	status = OSKextLoadKextWithIdentifier("com.apple.filesystems.apfs");
	if (status != kOSReturnSuccess) {
		panic("SourceStorage: APFS load failed %x", status);
	}

	void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
	if (!handle) {
		panic("SourceStorage: cannot begin class registration");
	}
	source_storage_base_init();
	source_storage_ufs_init();
	source_storage_ram_init();
	status = OSMetaClass::postModLoad(handle);
	if (status != kOSReturnSuccess) {
		panic("SourceStorage: class registration failed %x", status);
	}

	OSDictionary *matching = IOService::serviceMatching("IOPlatformExpertDevice");
	IOService *provider = matching ? IOService::waitForMatchingService(matching, 5000000000ULL) : nullptr;
	if (!provider) {
		panic("SourceStorage: platform root unavailable");
	}

	storageDriver = native_ufs_source_create();
	if (!storageDriver) {
		panic("SourceStorage: cannot allocate UFS service");
	}
	const char *step = !storageDriver->init() ? "init" : !storageDriver->attach(provider) ? "attach"
	    : !storageDriver->start(provider) ? "start" : nullptr;
	if (step) {
		panic("SourceStorage: UFS %s failed (root step %u: %s)", step, native_ufs_root_step,
		    native_ufs_root_failure ? native_ufs_root_failure : "no reason recorded");
	}

	printf("SourceStorage: UFS started through public IOStorageFamily interface\n");
	start_data_disk(provider);
}
