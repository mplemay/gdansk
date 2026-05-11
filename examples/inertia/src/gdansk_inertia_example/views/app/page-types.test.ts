import type { RootPageProps } from "@gdansk/types";

declare const props: RootPageProps;

props.metrics[0]?.label.toUpperCase();
props.activity?.map((item) => item.toUpperCase());
props.sessionToken?.toUpperCase();

// @ts-expect-error - generated page props should reject unknown metric fields.
props.metrics[0]?.missing;

// @ts-expect-error - generated page props should reject unknown top-level props.
props.unknownProp;
