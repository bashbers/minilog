# Model care records as explicit, extensible types

Care records will share a stable relational table, with a one-to-one detail table and validated schema for each built-in type. Adding built-in types requires an Alembic migration and matching backend and frontend registrations; household-defined custom types are deferred. This favors database constraints, reliable summaries, migrations, and exports over schema-free JSON customization.
