# Easy Property Management — Operator manual

This manual explains the local application as implemented on **October 14, 2026**. Start with the daily-use chapters if someone has already installed it for you. Installation and data-administration steps are marked for the person maintaining your computer's application setup.

The app records and helps you review property-management work. You remain responsible for confirming actions and recording what happened outside the app. It runs for one operator on the local computer, uses US properties and USD, and does not initiate payments or send messages.

## Start here

| Your goal | Read |
| --- | --- |
| Deploy a built wheel on a fresh VM | [VM deployment](deployment.md) |
| Install, configure, start, stop or update | [Installation and setup](installation.md) |
| Understand navigation, Home, saved forms and everyday routine | [Daily operation](daily-operation.md) |
| Set up properties, owners, tenants and service providers | [Portfolio and people](portfolio-and-people.md) |
| Manage leases, renewals, termination and inspections | [Leases and inspections](leases-and-inspections.md) |
| Record rent, expenses, deposits, prepaid checks and owner reports | [Money](money.md) |
| Handle repairs, appointments, quotes and owner concerns | [Maintenance and owner concerns](maintenance.md) |
| Track Tasks, waiting, conversations, documents and source evidence | [Tasks, communications and evidence](tasks-and-evidence.md) |
| Change appearance/navigation and configure available AI | [Settings and AI](settings-and-ai.md) |
| Back up, restore, relocate data and configure optional remote files | [Data protection and recovery](data-and-recovery.md) |
| Handle errors, conflicts or an uncertain save | [Troubleshooting](troubleshooting.md) |
| Find an uncommon action or look up a term | [Operation index](operation-index.md), [Glossary](glossary.md) |

## First portfolio checklist

1. Have the installer configure an external workspace and prove a backup/restore path.
2. Set your preferred appearance and navigation.
3. Enter client-owner and tenant identities, then properties and ownership relationships.
4. Confirm each Space's occupancy and availability; unknown information requires review.
5. Enter each lease, review it and explicitly execute it when appropriate.
6. Separately preview/confirm the rent schedule and record actual rent/deposit receipts.
7. Add providers, existing issues and follow-ups. Record useful conversations and evidence.
8. Review Home and information coverage. Missing setup is not resolved by marking a Task complete.

## Available versus planned

Home now provides live Needs action, Waiting, Upcoming, appointments, information review, inventory and recorded-money summaries. Snapshot caching and Dashboard cron are not installed in the current implementation; live reads passed the performance gate.

Current workflows include manual records, source evidence and AI configuration/review infrastructure. The current production AI registries have no qualified production adapters/actions/approval handlers. A configuration screen is not a promise that generation or approval is available.

Do not use the visual demo as a list of working features. Legal/HOA workflows, Excel/Google Sheets imports, connected assistants, issue-proposal review, showing integration and broader owner accounting retain separate delivery scope. Instructions here do not describe those future screens as available.

This is an operator guide. Developers can use the separate [developer documentation](../docs/README.md); release builders can use the [build/package instructions](../README.md#production-build-and-packaging-instructions).
