---
description: How to validate network configuration
---
# Validating Configuration

Whenever you modify any `.json` configuration file governing Service Discovery or endpoints, perform the following validation:

1. **Ensure Semantic Correctness**
   - Run the Config Validator skill on your file:
     `python tools/fusion/config_validator.py <path_to_config>`
   - This prevents port collisions or duplicate service instances, which cause sporadic runtime bugs!
   - Review `.agent/skills/config_validator/SKILL.md` for more details.

2. **Verify Binding Constraints**
   - Verify manually that no hardcoded fallback IPs like `127.0.0.1`, `::1` or `0.0.0.0` exist.
   - Runtimes should only bind to IP definitions explicit in the `config.json` file.
   - Read `.agent/rules/network_binding.md` for guidance.
