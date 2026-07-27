import 'axios'

declare module 'axios' {
  export interface AxiosRequestConfig<D = any> {
    /** Skip the application-wide loading bar for background refreshes. */
    silent?: boolean
  }
}
