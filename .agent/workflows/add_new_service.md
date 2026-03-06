---
description: How to add a new service
---
# Adding a New Service

When asked to add a new SOME/IP service to the system, follow these steps:

1. **Find an available Service ID**
   - Run the ID Manager skill to find the next available ID: `python tools/id_manager/manager.py`
   - Review `.agent/skills/id_manager/SKILL.md` if you need help.

2. **Create the IDL**
   - Define the service properties (Methods, Events, Data Types) in a new IDL python file.
   - Assign the `SERVICE_ID` discovered from step 1.
   - Respect the separation of IDL and Deployment. (Read `.agent/rules/id_management.md`)

3. **Deploy the Service via Configuration**
   - Add the required `interfaces` and `instances` definitions in the relevant `config.json`.
   - Ensure the runtime is binding purely to explicit interfaces. (Read `.agent/rules/network_binding.md` and `.agent/rules/coding.md`)

4. **Validate the Configuration**
   - Run the Config Validator to ensure no duplicate ID/Port clashes exist:
     `python tools/fusion/config_validator.py <path_to_config.json>`
   - Review `.agent/skills/config_validator/SKILL.md` if needed.

5. **Update Documentation**
   - Whenever you add a new service, you MUST update all relevant documentation, including any PlantUML (`.puml`) diagrams and architecture readmes, to accurately reflect the newly added service and its interactions.
