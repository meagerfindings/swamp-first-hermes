# Swamp-First Hermes

Swamp-First Hermes is a public foundation for a future Hermes integration with the Swamp CLI.

This repository intentionally contains only reusable source material and public documentation. It does **not** contain a deployment, scheduler or delivery configuration, runtime state, credentials, or information about any real environment.

## Current scope

The foundation currently establishes the public package boundary and its publication safeguards. It does not yet provide a Hermes plugin, Swamp command adapter, policy engine, installation workflow, or operational automation. Those capabilities are planned for later milestones.

## Public-boundary rules

Keep all environment-specific material outside this repository, including:

- deployment, scheduler, and delivery wiring;
- local configuration and runtime state;
- Swamp data, models, vaults, workflows, reports, and generated scripts;
- logs, credentials, tokens, and `.env` files.

The repository ignore rules provide defense in depth, but contributors remain responsible for reviewing staged changes before publication. See [the public-boundary policy](docs/public-boundary.md) for the full policy and review checklist.

## Contributing safely

Use generic placeholders in documentation and tests. Do not add real infrastructure details, identities, hostnames, paths, device labels, runtime output, or secrets. Keep deployment-specific configuration in a private location that is not versioned by this project.

## License

This project is licensed under the [MIT License](LICENSE).
