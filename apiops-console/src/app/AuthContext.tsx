import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, apiFetch, clearAccessToken, getAccessToken, saveAccessToken } from '../lib/api-client'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'expired'

export type CurrentUser = {
  id: string
  username: string
}

export type AuthFailureCode = 'INVALID_CREDENTIALS' | 'NETWORK' | 'GENERIC'

export type SignInResult =
  | { ok: true }
  | { ok: false; reason: AuthFailureCode }

type LoginResponse = {
  userId: number
  username: string
  tokenType: string
  accessToken: string
  expiresAt: string
}

type CurrentPrincipalResponse = {
  userId: number
  username: string
}

type AuthContextValue = {
  status: AuthStatus
  currentUser: CurrentUser | null
  signIn: (username: string, password: string) => Promise<SignInResult>
  signOut: () => void
  expireSession: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function toCurrentUser(principal: CurrentPrincipalResponse): CurrentUser {
  return {
    id: String(principal.userId),
    username: principal.username,
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() => getAccessToken() ? 'loading' : 'unauthenticated')
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)

  const expireSession = useCallback(() => {
    clearAccessToken()
    setCurrentUser(null)
    setStatus('expired')
  }, [])

  const signOut = useCallback(() => {
    clearAccessToken()
    setCurrentUser(null)
    setStatus('unauthenticated')
  }, [])

  const restoreSession = useCallback(async () => {
    if (!getAccessToken()) {
      setStatus('unauthenticated')
      return
    }

    try {
      const principal = await apiFetch<CurrentPrincipalResponse>('/api/v1/auth/me')
      setCurrentUser(toCurrentUser(principal))
      setStatus('authenticated')
    } catch (error) {
      if (isAbortError(error)) return
      clearAccessToken()
      setCurrentUser(null)
      setStatus(error instanceof ApiError && error.status === 401 ? 'expired' : 'unauthenticated')
    }
  }, [])

  useEffect(() => {
    void restoreSession()
  }, [restoreSession])

  const signIn = useCallback(async (username: string, password: string): Promise<SignInResult> => {
    setStatus('loading')
    setCurrentUser(null)

    try {
      const login = await apiFetch<LoginResponse>('/api/v1/auth/login', {
        authenticated: false,
        body: JSON.stringify({ username: username.trim(), password }),
        method: 'POST',
      })
      saveAccessToken(login.accessToken)

      const principal = await apiFetch<CurrentPrincipalResponse>('/api/v1/auth/me')
      setCurrentUser(toCurrentUser(principal))
      setStatus('authenticated')
      return { ok: true }
    } catch (error) {
      clearAccessToken()
      setCurrentUser(null)
      setStatus('unauthenticated')
      if (error instanceof ApiError && error.status === 401) return { ok: false, reason: 'INVALID_CREDENTIALS' }
      if (error instanceof ApiError && error.code === 'NETWORK_ERROR') return { ok: false, reason: 'NETWORK' }
      return { ok: false, reason: 'GENERIC' }
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    currentUser,
    expireSession,
    signIn,
    signOut,
    status,
  }), [currentUser, expireSession, signIn, signOut, status])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
