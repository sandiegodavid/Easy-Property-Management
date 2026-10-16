export function propertyUnitsLabel(layout: string): "Home" | "Office" | "Suites" {
  return layout === "single_space" ? "Home" : layout === "whole_office" ? "Office" : "Suites";
}

export function rentableUnitLabel(kind: string): "home" | "office" | "suite" {
  return kind === "whole_home" ? "home" : kind === "whole_office" ? "office" : "suite";
}
