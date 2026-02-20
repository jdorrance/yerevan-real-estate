export interface ListingRaw {
  id: number;
  url?: string;
  title?: string;
  price_usd?: number | string | null;
  city?: string;
  district?: string;
  street?: string;
  parsed_address_number?: string;
  bathrooms?: number | string | null;
  ceiling_height_m?: number | string | null;
  floors?: number | string | null;
  building_area_sqm?: number | string | null;
  land_area_sqm?: number | string | null;
  rooms?: number | string | null;
  building_type?: string;
  condition?: string;
  facilities?: string[] | string;
  amenities?: string[] | string;
  description?: string;
  photo_urls?: string[] | string;
  photo_count?: number | string | null;
  lat?: number | string | null;
  lng?: number | string | null;
  geocode_precision?: string;
}

export interface Listing {
  id: number;
  url: string;
  lat: number;
  lng: number;
  price: number | null;
  area: number | null;
  land_area: number | null;
  rooms: number | null;
  bathrooms: number | null;
  ceiling_height: number | null;
  floors: number | null;
  street: string;
  district: string;
  building_type: string;
  condition: string;
  precision: string;
  facilities: string[];
  amenities: string[];
  description: string;
  photo_urls: string[];
  photo_count: number;
}

export interface AppConfig {
  eu: { lat: number; lng: number };
}

export interface FilterValues {
  minPrice: number;
  maxPrice: number;
  minArea: number;
  minRooms: number;
  district: string;
}
