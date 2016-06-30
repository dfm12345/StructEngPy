# -*- coding: utf-8 -*-
"""
Created on Thu Jun 23 21:32:57 2016

@author: HZJ
"""
import sqlite3
import numpy as np
import scipy
import scipy.sparse as sp
import scipy.sparse.linalg as sl
from scipy import linalg
import Material,Section,Node,Beam
import DataManager.Definition as dd
import DataManager.Modeling.Nodes as dmn
import DataManager.Definition.Properties.Materials as ddpm
import DataManager.Definition.Properties.BeamSections as ddpb

class Model:
    def __init__(self,db):
        self.database=db
        
    def Save(self):
        return

    def Assemble(self,path):
        """
        Assemble matrix
        Writing the matrix to the disk
        """
        #*************************************************Modeling**************************************************/
        #Q345
        self.materials=[]
        self.sections=[]
        self.nodes=[]
        self.beams=[]
        
        self.materials.append(Material.Material(2.000E11, 0.3, 7849.0474, 1.17e-5))
        #H200x150x8x10
        self.sections.append(Section.Section(self.materials[0], 4.800E-3, 1.537E-7, 3.196E-5, 5.640E-6))
        conn=sqlite3.connect(self.database)
        nodesDf=dmn.GetNodesCoordiniate(conn)
        conn.close()
        for i in range(nodesDf.shape[0]):
            n=nodesDf.ix[i]            
            node=Node.Node(n['X'],n['Y'],n['Z'])
            self.nodes.append(node)
        for i in range(len(self.nodes)-1):
            self.beams.append(Beam.Beam(self.nodes[i], self.nodes[i+1], self.sections[0]))
        #loads
        #double f[6] = { 0,0,-100000,0,0,0 }
        qi=(0,0,-10,0,0,0)
        qj=(0,0,-10,0,0,0)
        #double d[6] = { 1,0,0,0,0,0 }
        self.beams[0].SetLoadDistributed(qi, qj)
        #beams[3].SetLoadDistributed(qi, qj)
        #nodes[3].SetLoad(f)
        #nodes[0].SetDisp(d)
        #supports
        res1 = [True]*6
        res2 = [False]*6
        res3 = [False,True, True, True, True, True ]
        self.nodes[0].SetRestraints(res1)
        self.nodes[1].SetRestraints(res2)
        #nodes[5].SetRestraints(res1)
        #releases
        #beams[3].releaseJ[4] = True
#        self.beams[3].releaseJ[5] = True
        #*************************************************Modeling**************************************************/
        
        nid = 0
        # Dynamic space allocate
        Kmat = np.zeros((len(self.nodes)*6, len(self.nodes)*6))
        Mmat = np.zeros((len(self.nodes)*6, len(self.nodes)*6))
        Fvec = np.zeros(len(self.nodes)*6)
        Dvec = np.zeros(len(self.nodes)*6)

        #Nodal load and displacement, and reset the index
        for node in self.nodes:
            node.id = nid
            load = np.array(node.load)
            Fvec[nid * 6: nid * 6 + 6] = np.dot(node.TransformMatrix().transpose(),load)
            for i in range(6):
                if node.disp[i] != 0:
                    Dvec[nid * 6 + i] = node.disp[i]
            nid+=1
        nid = 0
        #Beam load and displacement, and reset the index
        for beam in self.beams:
            beam.Id = nid
            i = beam.nodeI.id
            j = beam.nodeJ.id
            T=np.matrix(beam.TransformMatrix())
            Tt = T.transpose()

            #Transform matrix
            Vl=np.matrix(beam.localCsys.TransformMatrix())
            V=np.zeros((6, 6))
            V[:3,:3] =V[3:,3:]= Vl
            Vt = V.transpose()

            #Static condensation to consider releases
            Kij=np.zeros((12, 12))
            Mij=np.zeros((12, 12))
            rij=np.zeros(12)
            Kij, rij, Mij = beam.StaticCondensation(Kij, rij, Mij)

            #Assemble nodal force vector
            Fvec[i*6:i*6+6] += np.dot(Vt,rij[:6])
            Fvec[j*6:j*6+6] += np.dot(Vt,rij[6:])

            #Assemble Total Stiffness Matrix
            Ke = np.dot(np.dot(Tt,Kij),T)
            Keii = Ke[:6,:6]
            Keij = Ke[:6,6:]
            Keji = Ke[6:,:6]
            Kejj = Ke[6:,6:]
            Kmat[i*6:i*6+6, i*6:i*6+6] += Keii
            Kmat[i*6:i*6+6, j*6:j*6+6] += Keij
            Kmat[j*6:j*6+6, i*6:i*6+6] += Keji
            Kmat[j*6:j*6+6, j*6:j*6+6] += Kejj

            #Assembel Mass Matrix        
            Me = np.dot(np.dot(Tt,Mij),T)
            Meii = Me[:6,:6]
            Meij = Me[:6,6:]
            Meji = Me[6:,:6]
            Mejj = Me[6:,6:]
            Mmat[i*6:i*6+6, i*6:i*6+6] += Meii
            Mmat[i*6:i*6+6, j*6:j*6+6] += Meij
            Mmat[j*6:j*6+6, i*6:i*6+6] += Meji
            Mmat[j*6:j*6+6, j*6:j*6+6] += Mejj

            nid+=1
        
        scipy.io.mmwrite(path+'K.mtx',sp.coo_matrix(Kmat))
        scipy.io.mmwrite(path+'M.mtx',sp.coo_matrix(Mmat))
        scipy.io.mmwrite(path+'F.mtx',sp.coo_matrix(Fvec))
        scipy.io.mmwrite(path+'D.mtx',sp.coo_matrix(Dvec))

    def isAssembled(self):
#        if self.Kmat == None:
#            return False
        return True

    def K(self):
        return self.Kmat

    def F(self):
        return self.Fvec

    def EliminateMatrix(self,path,mass=False):
        """
        return 
        K_bar: sparse matrix
        F_bar: sparse matrix
        M_bar: sparse matrix
        index: vector
        """
        Kmat=scipy.io.mmread(path+'K.mtx')
        Mmat=scipy.io.mmread(path+'M.mtx')
        Fvec=scipy.io.mmread(path+'F.mtx').toarray()[0]
        Dvec=scipy.io.mmread(path+'D.mtx').toarray()[0]
        if mass==False:
            k = Kmat.todense()
            f = Fvec
            Id=np.arange(len(f))
            nRemoved=0
            i=0
            for node in self.nodes:
                for j in range(6):
                    if node.restraints[j] == True or node.disp[j] != 0:
                        k=np.delete(k,i*6+j-nRemoved,axis=0)
                        k=np.delete(k,i*6+j-nRemoved,axis=1)
                        f=np.delete(f,i*6+j-nRemoved)
                        Id=np.delete(Id,i*6+j-nRemoved)
                        nRemoved+=1
                i+=1
            K_ = k
            F_ = f
            index = Id
            return K_,F_,Dvec,index
        else:
            k = Kmat
            m = Mmat
            f = Fvec
            Id=np.arange(len(f))
            nRemoved = 0
            i=0
            for node in self.nodes:
                for j in range(6):
                    if node.restraints[j] == True or node.disp[j]!=0:
                        k=np.delete(k,i*6+j-nRemoved,axis=0)
                        k=np.delete(k,i*6+j-nRemoved,axis=1)
                        f=np.delete(f,i*6+j-nRemoved)
                        m=np.delete(m,i*6+j-nRemoved,axis=0)
                        m=np.delete(m,i*6+j-nRemoved,axis=1)
                        Id=np.delete(Id,i*6+j-nRemoved)
                        nRemoved+=1
                i+=1
            K_ = k
            M_ = m
            F_ = f
            index = Id
            return K_,M_,F_,Dvec,index

    def SolveLinear(self,path):
        if not self.isAssembled():
            raise Exception('Not assemble yet!!')
        
        K_bar,F_bar,Dvec,index = self.EliminateMatrix(path)
        try:
            #sparse matrix solution         
            delta_bar = sl.spsolve(K_bar,F_bar)
            print('HERE!')
            delta = delta_bar
            f=np.zeros(len(self.beams)*12)
           
            #fill original displacement vector
            prev = 0
            for idx in index:
                gap=idx-prev
                if gap>0:
                    delta=np.insert(delta,prev,[0]*gap)
                prev = idx + 1               
                if idx==index[-1] and idx!=len(self.nodes)-1:
                    delta = np.insert(delta,prev, [0]*(len(self.nodes)*6-prev))
            delta += Dvec

            #calculate element displacement and forces
            for beam in self.beams:
                Kij_bar=np.zeros((12, 12))
                rij_bar=np.zeros((12,1))
                Kij_bar,rij_bar=beam.StaticCondensation(Kij_bar, rij_bar)
                uij=np.zeros(12)
                fij=np.zeros(12)
                
                i=0
                for node in self.nodes:
                    if node is beam.nodeI:
                        iend=i
                    i+=1
                i=0
                for node in self.nodes:
                    if node is beam.nodeJ:
                        jend=i
                    i+=1
                
                uij[:6]=delta[iend*6:iend*6+6]
                uij[6:]=delta[jend*6:jend*6+6]
                uij = np.dot(beam.TransformMatrix(),uij)
                
                fij = np.dot(Kij_bar,uij) + beam.NodalForce()
                for i in range(6):
                    if beam.releaseI[i] == True:
                        fij[i] = 0
                    if beam.releaseJ[i] == True:
                        fij[i + 6] = 0
                #beam.ID
                i=0
                for b in self.beams:
                    if beam is b:
                        bid=i
                    i+=1
                f[bid*12:bid*12+12] = fij
            for n in range(len(self.nodes)):
                print("Disp of node "+str(n)+':')
                for i in range(n * 6,n * 6 + 6):
                   print("delta[%d"%(i - n * 6) +"]=%f"%delta[i])

            for n in range(len(self.beams)):
                print("Force of beam " +str(n)+ ':')
                for i in range(n*12,n*12+12):
                    print("f[%d"%(i - n * 12)+"]=%f"%f[i])
        except Exception as e:
            print(e)
            return False
        return True

    def SolveModal(self,path,k):
        if not self.isAssembled():
            raise Exception('Not assemble yet!!')           
        K_bar,M_bar,F_bar,index,Dvec = self.EliminateMatrix(path,True)

        try:
            #general eigen solution, should be optimized later!!
            A=sp.csr_matrix(K_bar)
            B=sp.csr_matrix(M_bar)
            
            omega2s,mode = sl.eigsh(A,k,B)
        
            for omega2 in omega2s:
                print(2*3.14/np.sqrt(omega2))

            #extract vibration mode
            delta_bar = np.linalg.norm(mode)/np.linalg.norm(mode)
            delta=delta_bar
            f=np.zeros(len(self.beams)*12)
            
            print('HERE!!!!')
            #fill original displacement vector
            prev = 0
            for idx in index:
                gap=idx-prev
                if gap>0:
                    delta=np.insert(delta,prev,[0]*gap)
                prev = idx + 1               
                if idx==index[-1] and idx!=len(self.nodes)-1:
                    delta = np.insert(delta,prev, [0]*(len(self.nodes)*6-prev))
            delta += Dvec

            #calculate element displacement and forces
            for beam in self.beams:
                Kij_bar=np.zeros((12, 12))
                rij_bar=np.zeros(12)
                Kij_bar,rij_bar=beam.StaticCondensation(Kij_bar,rij_bar)
                uij=np.zeros(12)
                fij=np.zeros(12)
                
                i=0
                for node in self.nodes:
                    if node is beam.nodeI:
                        iend=i
                    i+=1
                i=0
                for node in self.nodes:
                    if node is beam.nodeJ:
                        jend=i
                    i+=1
                
                uij[:6]=delta[iend*6:iend*6+6]
                uij[6:]=delta[jend*6:jend*6+6]
                uij = np.dot(beam.TransformMatrix(),uij)

                fij = np.dot(Kij_bar,uij) + beam.NodalForce()
                for i in range(6):
                    if beam.releaseI[i] == True:
                        fij[i] = 0
                    if beam.releaseJ[i] == True:
                        fij[i + 6] = 0
                
                #beam.ID
                i=0
                for b in self.beams:
                    if beam is b:
                        bid=i
                    i+=1  
            
                f[bid * 12,bid*12+12]=fij
            for n in range(len(self.nodes)):
                print("Disp of node " +str(n)+ ':')
                for i in range(n*6, n*6+6):
                    print("delta["+str(i-n*6)+"]="+str(delta[i]))
            for n in range(len(self.beams)):
                print( "Force of beam "+str(n)+':')
                for i in range(n*12, n*12 + 12):
                    print("f[" +str(i-n*12)+"]=" +str(f[i]))
        except Exception as e:
            print(str(e))
            return False
        return True

    def SetMass(self):
        for beam in self.beams:
            beam.nodeI.mass += beam.section.A*beam.section.material.gamma*beam.Length() / 2
            beam.nodeJ.mass += beam.section.A*beam.section.material.gamma*beam.Length() / 2
        return False
        
    def Test(self):
        #*************************************************Modeling**************************************************/
        #Q345
        materials=[]
        sections=[]
        nodes=[]
        beams=[]
        
        materials.append(Material.Material(2.000E11, 0.3, 7849.0474, 1.17e-5))
        #H200x150x8x10
        sections.append(Section.Section(materials[0], 4.800E-3, 1.537E-7, 3.196E-5, 5.640E-6))
        nodes.append(Node.Node(0, 0, 0))
        nodes.append(Node.Node(5, 0, 0))
        for i in range(len(nodes)-1):
            beams.append(Beam.Beam(nodes[i], nodes[i+1], sections[0]))
        #loads
        #double f[6] = { 0,0,-100000,0,0,0 }
        qi=(0,0,-10,0,0,0)
        qj=(0,0,-10,0,0,0)
        #double d[6] = { 1,0,0,0,0,0 }
        beams[0].SetLoadDistributed(qi, qj)
        #beams[3].SetLoadDistributed(qi, qj)
        #nodes[3].SetLoad(f)
        #nodes[0].SetDisp(d)
        #supports
        res1 = [True]*6
        res2 = [False]*6
        res3 = [False,True,True,True,True,True]
        nodes[0].SetRestraints(res1)
        nodes[1].SetRestraints(res2)
        #nodes[5].SetRestraints(res1)
        #releases
        #beams[3].releaseJ[4] = True
#        self.beams[3].releaseJ[5] = True
        #*************************************************Modeling**************************************************/
        ID=0
        ns=[]
        for node in nodes:
            ns.append([ID,node.x,node.y,node.z])
            ID+=1
        conn=sqlite3.connect(self.database)
        try:
            dmn.CreateTable(conn,commit=False)
            dmn.AddCartesian(conn,ns,commit=False)
            ddpm.CreateTable(conn,commit=False)
            ddpm.AddQuick(conn,'GB','Q345',commit=False)
            
            ddpb.CreateTable(conn,commit=False)
            ddpb.AddQuick(conn,'Q345','H400x200x12x14')
            
            conn.commit()
        finally:
            conn.close()
        
        
if __name__=='__main__':     
    file='C:\\huan\\Test\\Test.sqlite'
    path='C:\\huan\\Test\\'
    m=Model(file)
#    m.Test()
    m.Assemble(path)
    m.SolveLinear(path)
#    m.SolveModal(path,k=1)