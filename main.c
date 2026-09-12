#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libgen.h>
#include <mach-o/dyld.h>

int main(int argc, char *argv[]) {
    char exe_path[1024];
    uint32_t size = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &size) != 0) {
        fprintf(stderr, "Error: Could not determine executable path\n");
        return 1;
    }

    char *macos_dir = dirname(exe_path);
    char resources_dir[1024];
    snprintf(resources_dir, sizeof(resources_dir), "%s/../Resources", macos_dir);

    // Initialize Python 3.11 Config
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0; // Prevent Python from intercepting macOS -psn flags

    PyStatus status = PyConfig_SetBytesString(&config, &config.program_name, argv[0]);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        return 1;
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        return 1;
    }

    char boot_code[4096];
    snprintf(boot_code, sizeof(boot_code),
        "import sys, os\n"
        "res_dir = '%s'\n"
        "for p in [res_dir, os.path.join(res_dir, 'core'), '/Users/digvijayasatapathy/HeyMelody_unpacked']:\n"
        "    if os.path.isdir(p) and p not in sys.path:\n"
        "        sys.path.insert(0, p)\n"
        "try:\n"
        "    import buds_app\n"
        "    buds_app.main()\n"
        "except Exception as e:\n"
        "    import traceback\n"
        "    traceback.print_exc()\n"
        "    sys.exit(1)\n",
        resources_dir
    );

    int ret = PyRun_SimpleString(boot_code);
    Py_Finalize();
    return ret;
}
