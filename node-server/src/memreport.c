// memreport.c - per-mapping resident memory report (debugging aid)
//
// Walks /proc/self/maps and asks mincore(2) which pages of each mapping are
// in memory. mincore() only reports residency; it never faults pages in, so
// taking a report doesn't disturb the working set it's measuring.
//
// Caveat: for file-backed mappings (library text, etc.) mincore() reports
// whether the page is in the page cache, not whether *this* process has
// touched it. Pages of libc that other processes keep hot will show up as
// resident here even if gm-node never used them. Anonymous mappings (heap,
// stacks, bss) are accurate.

// mincore() is a BSD/Linux extension hidden by the strict feature macros in
// gm-node.h, so ask for the platform's full namespace first.
#define _NETBSD_SOURCE
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE

#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <unistd.h>
#include <sys/mman.h>

#include "gm-node.h"

#define MAPS_LINE_SIZE 512
#define MAX_OBJECTS 64
#define VEC_PAGES 256 // pages checked per mincore() call

struct object_total {
    char path[MAPS_LINE_SIZE];
    unsigned long virt_kb;
    unsigned long res_kb;
};

// static so that taking a report doesn't grow the heap we're measuring
static struct object_total objects[MAX_OBJECTS];
static unsigned char vec[VEC_PAGES];

static atomic_bool report_requested = false;

void gm_request_memory_report(void) {
    atomic_store(&report_requested, true);
}

bool gm_memory_report_pending(void) {
    return atomic_exchange(&report_requested, false);
}

// Count resident pages in [start, end). Returns -1 if mincore() fails.
static long resident_pages(unsigned long start, unsigned long end, long pagesize) {
    long count = 0;
    unsigned long addr = start;
    while (addr < end) {
        size_t npages = (end - addr) / pagesize;
        if (npages > VEC_PAGES) npages = VEC_PAGES;
        // Linux wants unsigned char *, the BSDs want char *
        if (mincore((void *)addr, npages * pagesize, (void *)vec) != 0) {
            return -1;
        }
        for (size_t i = 0; i < npages; i++) {
            if (vec[i] & 1) count++;
        }
        addr += npages * pagesize;
    }
    return count;
}

static void add_to_object(int *n_objects, const char *path, unsigned long virt_kb, unsigned long res_kb) {
    int i;
    for (i = 0; i < *n_objects; i++) {
        if (strcmp(objects[i].path, path) == 0) break;
    }
    if (i == *n_objects) {
        if (*n_objects == MAX_OBJECTS) return;
        strncpy(objects[i].path, path, MAPS_LINE_SIZE - 1);
        objects[i].path[MAPS_LINE_SIZE - 1] = '\0';
        objects[i].virt_kb = objects[i].res_kb = 0;
        (*n_objects)++;
    }
    objects[i].virt_kb += virt_kb;
    objects[i].res_kb += res_kb;
}

void gm_memory_report(FILE *out, const char *label) {
    FILE *maps = fopen("/proc/self/maps", "r");
    if (maps == NULL) {
        fprintf(out, "memory report: can't open /proc/self/maps (is procfs mounted?)\n");
        return;
    }

    long pagesize = sysconf(_SC_PAGESIZE);
    unsigned long total_virt = 0, total_res = 0;
    int n_objects = 0;
    char line[MAPS_LINE_SIZE];

    fprintf(out, "\n--- memory report: %s ---\n", label);
    fprintf(out, "%-17s %-4s %8s %8s  %s\n", "range", "perm", "virt KB", "res KB", "object");

    while (fgets(line, sizeof(line), maps) != NULL) {
        unsigned long start, end;
        char perms[8];
        int path_offset = 0;
        if (sscanf(line, "%lx-%lx %7s %*s %*s %*s %n", &start, &end, perms, &path_offset) < 3) {
            continue;
        }
        line[strcspn(line, "\n")] = '\0';
        const char *path = path_offset > 0 && line[path_offset] != '\0' ? line + path_offset : "[anon]";

        // ---p reservations and guard pages are never backed; skip them
        if (strncmp(perms, "---", 3) == 0) continue;

        unsigned long virt_kb = (end - start) / 1024;
        long pages = resident_pages(start, end, pagesize);
        unsigned long res_kb = pages < 0 ? 0 : (unsigned long)pages * (pagesize / 1024);

        if (pages < 0) {
            fprintf(out, "%08lx-%08lx %-4s %8lu %8s  %s\n", start, end, perms, virt_kb, "?", path);
        }
        else {
            fprintf(out, "%08lx-%08lx %-4s %8lu %8lu  %s\n", start, end, perms, virt_kb, res_kb, path);
        }

        total_virt += virt_kb;
        total_res += res_kb;
        add_to_object(&n_objects, path, virt_kb, res_kb);
    }
    fclose(maps);

    fprintf(out, "\n%8s %8s  %s\n", "virt KB", "res KB", "object (totals)");
    for (int i = 0; i < n_objects; i++) {
        fprintf(out, "%8lu %8lu  %s\n", objects[i].virt_kb, objects[i].res_kb, objects[i].path);
    }
    fprintf(out, "%8lu %8lu  total\n", total_virt, total_res);
    fprintf(out, "(file-backed res KB = pages in the page cache, possibly shared with other processes)\n\n");
    fflush(out);
}
